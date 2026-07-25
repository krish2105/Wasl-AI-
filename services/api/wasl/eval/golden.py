"""Scan the golden set and score Wasl against its labels.

Separate from `eval.run` because this one crawls: 22 observable sites at 0.5
req/s is tens of minutes, and it sends real requests to real third parties.
Results are cached to `seeds/golden/results.json` so the metrics table can be
rebuilt without re-crawling anyone.

The circularity caveat lives in `labels.yaml` and is carried through into every
metric name this module produces. Nothing here silently upgrades a model-
authored label into ground truth.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from wasl.crawler.detectors import extract_all
from wasl.crawler.fetch import Crawler, CrawlRefused
from wasl.crawler.policy import Budget, repo_root
from wasl.eval.metrics import band_distance, capability_precision_recall
from wasl.graph.build import store_from_records
from wasl.graph.nodes import critic as critic_node
from wasl.graph.nodes import extract as extract_node
from wasl.graph.nodes import induce as induce_node
from wasl.graph.nodes import score as score_node
from wasl.graph.nodes import synthesize as synthesize_node
from wasl.graph.nodes.crawl import summarise
from wasl.graph.state import WaslState
from wasl.llm.router import ModelRouter

logger = logging.getLogger(__name__)

LABELS = repo_root() / "seeds" / "golden" / "labels.yaml"
RESULTS = repo_root() / "seeds" / "golden" / "results.json"

# Different domains, so these run concurrently without breaching the per-domain
# rate limit — that limiter is a shared Redis reservation, not a local sleep.
MAX_CONCURRENT_SITES = 4


def load_labels() -> dict[str, Any]:
    return yaml.safe_load(LABELS.read_text())


async def scan_one(site: dict[str, Any], router: ModelRouter) -> dict[str, Any]:
    """Crawl and score one golden site. Never raises — a failure is a datapoint."""
    started = time.perf_counter()
    name, url = site["name"], site["url"]

    try:
        async with Crawler(budget=Budget.INTERACTIVE) as crawler:
            pages, artifacts = await crawler.crawl(url)
    except CrawlRefused as exc:
        return {"name": name, "url": url, "error": f"refused: {exc.reason}", "seconds": 0}
    except Exception as exc:
        return {"name": name, "url": url, "error": f"{type(exc).__name__}: {exc}", "seconds": 0}

    store = extract_all(pages, artifacts)
    state = WaslState(
        job_id=f"golden-{uuid.uuid4().hex[:6]}",
        root_url=url,
        domain=artifacts.domain,
        pages=[summarise(p) for p in pages],
        evidence=extract_node.to_records(store),
    )
    rebuilt = store_from_records(state.evidence)

    try:
        induced = await induce_node.induce(state, store=rebuilt, router=router)
        state = state.model_copy(update={"candidate_capabilities": induced.get("candidate_capabilities", [])})
        synthesized = await synthesize_node.synthesize(state, store=rebuilt, router=router)
        state = state.model_copy(update={"candidate_capabilities": synthesized.get("candidate_capabilities", [])})
        critiqued = await critic_node.critique(state, store=rebuilt, router=router)
        state = state.model_copy(
            update={
                "accepted_capabilities": critiqued.get("accepted_capabilities", []),
                "rejections": critiqued.get("rejections", []),
            }
        )
    except Exception as exc:
        logger.warning("%s: model stage failed: %s", name, exc)

    scored = await score_node.score(state, store=rebuilt)
    score = scored.get("score") or {}

    return {
        "name": name,
        "url": url,
        "seconds": round(time.perf_counter() - started, 1),
        "pages_ok": state.pages_ok,
        "pages_robots_blocked": state.pages_robots_blocked,
        "evidence": len(rebuilt),
        "total": score.get("total"),
        "max_possible": score.get("max_possible"),
        "percentage": score.get("percentage"),
        "band": score.get("band"),
        "confidence": score.get("confidence"),
        "predicted_capabilities": [f"{c.verb} {c.noun}" for c in state.accepted_capabilities],
        "rejections": len(state.rejections),
        "error": None,
    }


async def run_scans(limit: int | None = None) -> list[dict[str, Any]]:
    labels = load_labels()
    sites = [s for s in labels["sites"] if s.get("observable")]
    if limit:
        sites = sites[:limit]

    router = ModelRouter()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SITES)
    done = 0

    async def guarded(site: dict[str, Any]) -> dict[str, Any]:
        nonlocal done
        async with semaphore:
            result = await scan_one(site, router)
            done += 1
            marker = "!" if result.get("error") else "+"
            print(
                f"  {marker} [{done:>2}/{len(sites)}] {site['name']:<26} "
                f"{result.get('total', '—')}/{result.get('max_possible', '—')} "
                f"{result.get('band') or 'suppressed':<14} {result['seconds']}s"
            )
            return result

    print(f"scanning {len(sites)} observable golden sites "
          f"({MAX_CONCURRENT_SITES} concurrent, 0.5 req/s per domain)\n")
    results = await asyncio.gather(*(guarded(s) for s in sites))

    RESULTS.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {RESULTS.relative_to(repo_root())}")
    return results


def compute_metrics(results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Score Wasl against the labels. Returns metric values plus their denominators."""
    labels = load_labels()
    by_name = {s["name"]: s for s in labels["sites"]}

    if results is None:
        if not RESULTS.exists():
            return {"available": False, "reason": "no results — run `python -m wasl.eval.golden --scan`"}
        results = json.loads(RESULTS.read_text())

    usable = [r for r in results if not r.get("error") and r.get("total") is not None]
    if not usable:
        return {"available": False, "reason": "every golden scan failed"}

    precisions: list[float] = []
    recalls: list[float] = []
    band_exact = 0
    band_within_1 = 0
    band_scored = 0
    per_site: list[dict[str, Any]] = []

    for result in usable:
        label = by_name.get(result["name"])
        if not label or not label.get("capabilities"):
            continue

        p, r = capability_precision_recall(result["predicted_capabilities"], label["capabilities"])
        precisions.append(p)
        recalls.append(r)

        distance = band_distance(result.get("band"), label.get("expected_band"))
        if distance is not None:
            band_scored += 1
            band_exact += distance == 0
            band_within_1 += distance <= 1

        per_site.append(
            {
                "name": result["name"],
                "precision": round(p, 3),
                "recall": round(r, 3),
                "predicted_band": result.get("band"),
                "labelled_band": label.get("expected_band"),
                "band_distance": distance,
            }
        )

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    return {
        "available": True,
        "label_source": labels.get("label_source", "unknown"),
        "circular": bool(labels.get("circular")),
        "sites_scanned": len(usable),
        "sites_compared": len(per_site),
        "band_scored": band_scored,
        "capability_precision": mean(precisions),
        "capability_recall": mean(recalls),
        "band_accuracy_exact": round(band_exact / band_scored, 3) if band_scored else None,
        "band_accuracy_within_1": round(band_within_1 / band_scored, 3) if band_scored else None,
        "per_site": per_site,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="crawl the golden set (slow, hits real sites)")
    parser.add_argument("--limit", type=int, help="scan only the first N sites")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)-5s %(name)s: %(message)s",
    )

    results = asyncio.run(run_scans(args.limit)) if args.scan else None
    metrics = compute_metrics(results)

    if not metrics["available"]:
        print(metrics["reason"])
        return 1

    print(f"\n{'=' * 70}\nGOLDEN SET — {metrics['sites_scanned']} scanned, "
          f"{metrics['sites_compared']} compared\n{'=' * 70}")
    if metrics["circular"]:
        print("  label_source: model — these measure agreement with the labelling")
        print("  model, not correctness. Names carry judge_labelled_ for that reason.\n")

    for key in ("capability_precision", "capability_recall",
                "band_accuracy_exact", "band_accuracy_within_1"):
        value = metrics[key]
        print(f"  {key:<28} {value if value is not None else '—'}")

    print(f"\n  {'site':<26} {'prec':>5} {'rec':>5}  predicted → labelled")
    for row in sorted(metrics["per_site"], key=lambda r: -(r["recall"] or 0)):
        print(f"  {row['name']:<26} {row['precision']:>5} {row['recall']:>5}  "
              f"{str(row['predicted_band']):<14} → {row['labelled_band']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
