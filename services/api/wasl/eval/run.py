"""Run the evaluation and write the results into the README.

    uv run python -m wasl.eval.run
    uv run python -m wasl.eval.run --no-readme

Exit code is the gate: non-zero if any hard gate fails, so this belongs in CI.

What it can compute today, and what it cannot, is decided by whether ground truth
exists. The gates and operating metrics run against fixtures and generated
artifacts — no human input needed. Capability precision/recall and band accuracy
need `seeds/golden/labels.yaml` filled in by hand, and until it is they report
BLOCKED rather than a number. An invented denominator is worse than a missing
metric because it reads as evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from wasl.crawler.detectors import extract_all
from wasl.crawler.policy import repo_root
from wasl.eval.metrics import (
    BY_KEY,
    MIN_SAMPLES_FOR_A_CLAIM,
    EvalReport,
    MetricClass,
    MetricResult,
    Status,
    citation_validity,
    hallucinated_capability_rate,
    injection_recall,
    percentile,
    score_stability,
    state_changing_tool_rate,
)
from wasl.generators.packager import generate_all
from wasl.graph.build import store_from_records
from wasl.graph.nodes import critic as critic_node
from wasl.graph.nodes import extract as extract_node
from wasl.graph.nodes import induce as induce_node
from wasl.graph.nodes import score as score_node
from wasl.graph.nodes import synthesize as synthesize_node
from wasl.graph.nodes.crawl import summarise
from wasl.graph.state import WaslState
from wasl.llm.prompts.registry import all_prompts
from wasl.llm.router import ModelRouter, Role
from wasl.scoring.cli import load_fixture, neutral_artifacts
from wasl.security.injection import scan_html

logger = logging.getLogger(__name__)

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
LABELS_PATH = repo_root() / "seeds" / "golden" / "labels.yaml"
README_PATH = repo_root() / "README.md"

# Fixtures the harness scans end to end. Chosen to span the range the rubric has
# to discriminate across.
EVAL_FIXTURES = ("rich_site", "spa_site", "thin_site")

STABILITY_REPEATS = 3


def _labels_status() -> tuple[int, int, str]:
    """(total entries, labelled entries, reason if unusable)."""
    if not LABELS_PATH.exists():
        return 0, 0, "seeds/golden/labels.yaml does not exist"

    data = yaml.safe_load(LABELS_PATH.read_text()) or {}
    sites = data.get("sites") or []
    labelled = [s for s in sites if s.get("expected_band") and s.get("capabilities")]

    if not labelled:
        return (
            len(sites),
            0,
            f"labels.yaml has {len(sites)} entries but none are filled in — "
            "these metrics need hand-labelled ground truth",
        )
    return len(sites), len(labelled), ""


async def _scan_fixture(name: str, router: ModelRouter) -> dict:
    """Run the whole pipeline on one fixture and collect everything measurable."""
    started = time.perf_counter()

    page = load_fixture(name)
    artifacts = neutral_artifacts(page.final_url)
    pages = [page]
    store = extract_all(pages, artifacts)

    state = WaslState(
        job_id=f"eval-{name}-{uuid.uuid4().hex[:6]}",
        root_url=page.final_url,
        domain=artifacts.domain,
        pages=[summarise(page)],
        evidence=extract_node.to_records(store),
    )
    rebuilt = store_from_records(state.evidence)

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

    scored = await score_node.score(state, store=rebuilt)
    state = state.model_copy(update={"score": scored.get("score")})

    outcome = await generate_all(
        job_id=state.job_id,
        domain=artifacts.domain,
        site_name=name.replace("_", " ").title(),
        capabilities=[*state.accepted_capabilities, *state.candidate_capabilities],
        pages=state.pages,
        store=rebuilt,
        score=state.score,
        output_root=repo_root() / "data" / "artifacts" / "eval",
    )

    return {
        "name": name,
        "state": state,
        "store": rebuilt,
        "outcome": outcome,
        "seconds": time.perf_counter() - started,
    }


def _stability(name: str) -> float:
    """Repeat the deterministic half on identical input.

    Measures the rubric's own reproducibility. Against a fixture this should be
    exactly zero — and if it ever is not, the "deterministic scoring" claim is
    false and that is the single most important thing this harness can tell us.
    """
    totals: list[int] = []
    for _ in range(STABILITY_REPEATS):
        page = load_fixture(name)
        pages = [page]
        store = extract_all(pages, neutral_artifacts(page.final_url))
        from wasl.scoring.rubric import score_site, scoring_input_from_crawl

        totals.append(score_site(store, scoring_input_from_crawl(store, pages)).total)
    return score_stability(totals)


def _injection_recall() -> tuple[float, list[str]]:
    expected_path = FIXTURES / "injection_payloads.expected.yaml"
    html_path = FIXTURES / "injection_payloads.html"
    if not expected_path.exists() or not html_path.exists():
        return 0.0, ["fixture missing"]

    expected = yaml.safe_load(expected_path.read_text())
    want = {p["pattern_id"] for p in expected["payloads"]}
    found = {m.pattern_id for m in scan_html(html_path.read_text())}
    return injection_recall(want, found)


async def build_report(*, router: ModelRouter | None = None) -> EvalReport:
    router = router or ModelRouter()
    total_labels, labelled, blocked_reason = _labels_status()

    report = EvalReport(
        golden_set_size=total_labels,
        golden_labelled=labelled,
        model=router.describe_chain(Role.INDUCE).split(": ", 1)[-1],
        prompt_shas=all_prompts(),
        run_date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )

    scans = [await _scan_fixture(name, router) for name in EVAL_FIXTURES]

    # --- gates ---------------------------------------------------------------
    all_cited: list[str] = []
    known_ids: set[str] = set()
    all_capabilities = []
    for scan in scans:
        state = scan["state"]
        known_ids |= {e.id for e in scan["store"]}
        for capability in [*state.accepted_capabilities, *state.candidate_capabilities]:
            all_cited.extend(capability.evidence_ids)
            all_capabilities.append(capability)

    validity, dangling = citation_validity(all_cited, known_ids)
    report.results.append(
        MetricResult(
            BY_KEY["citation_validity"],
            validity,
            detail=f"{len(all_cited)} citation(s) across {len(scans)} scans",
        )
    )
    if dangling:
        report.failures.append(f"dangling evidence references: {dangling[:5]}")

    hallucinated, offenders = hallucinated_capability_rate(all_capabilities, known_ids)
    report.results.append(
        MetricResult(
            BY_KEY["hallucinated_capability_rate"],
            hallucinated,
            detail=f"{len([c for c in all_capabilities if c.accepted])} accepted capability/ies re-audited",
        )
    )
    if offenders:
        report.failures.append(f"hallucinated capabilities: {offenders}")

    state_changing, sc_offenders = state_changing_tool_rate(all_capabilities)
    report.results.append(
        MetricResult(BY_KEY["state_changing_tool_rate"], state_changing, detail="emitted tools audited")
    )
    if sc_offenders:
        report.failures.append(f"state-changing tools emitted: {sc_offenders}")

    generated = [s for s in scans if s["outcome"].artifacts.tool_count > 0 or s["state"].accepted_capabilities]
    if generated:
        imported = sum(1 for s in generated if s["outcome"].verification.imported)
        report.results.append(
            MetricResult(
                BY_KEY["generated_server_import_rate"],
                imported / len(generated),
                detail=f"{imported}/{len(generated)} generated servers imported in a clean subprocess",
            )
        )
        for scan in generated:
            if not scan["outcome"].verification.imported:
                report.failures.append(f"{scan['name']}: generated server failed to import")
    else:
        report.results.append(
            MetricResult(
                BY_KEY["generated_server_import_rate"],
                None,
                blocked_reason="no fixture produced an accepted capability to generate from",
            )
        )

    # --- tuning: the label-dependent three ------------------------------------
    from wasl.eval.golden import compute_metrics as golden_metrics

    golden = golden_metrics()
    key_map = {
        "capability_precision": "judge_labelled_capability_precision",
        "capability_recall": "judge_labelled_capability_recall",
        "band_accuracy_exact": "judge_labelled_band_accuracy_exact",
        "band_accuracy_within_1": "judge_labelled_band_accuracy_within_1",
    }

    for source_key, metric_key in key_map.items():
        if not golden.get("available"):
            report.results.append(
                MetricResult(BY_KEY[metric_key], None, blocked_reason=golden.get("reason", blocked_reason))
            )
            continue

        samples = golden["band_scored"] if source_key.startswith("band") else golden["sites_compared"]
        detail = (
            f"{samples} sites with a comparable band"
            if source_key.startswith("band")
            else f"{samples} of 30 golden sites compared"
        )
        report.results.append(
            MetricResult(BY_KEY[metric_key], golden.get(source_key), detail=detail, samples=samples)
        )

    if golden.get("available") and golden.get("circular"):
        report.notes.append(
            "The three label-dependent metrics are marked with an asterisk and named "
            "judge_labelled_*. seeds/golden/labels.yaml declares label_source: model, so "
            "they measure agreement with the labelling model rather than correctness. "
            "The four boolean label fields are independent observations and are not affected."
        )
    if golden.get("available"):
        report.notes.append(
            f"Band accuracy is computed over {golden['band_scored']} sites, not 30: eight of "
            "the golden set blocked automated access at labelling time and were left "
            "deliberately unlabelled rather than guessed."
        )

    recall, missed = _injection_recall()
    report.results.append(
        MetricResult(
            BY_KEY["injection_detection_recall"],
            recall,
            detail=f"{len(missed)} missed" if missed else "all seeded payloads caught",
        )
    )
    if missed and missed != ["fixture missing"]:
        report.failures.append(f"missed injection patterns: {missed}")

    # --- operating -----------------------------------------------------------
    report.results.append(
        MetricResult(
            BY_KEY["score_stability_max_delta"],
            max(_stability(name) for name in EVAL_FIXTURES),
            detail=f"{STABILITY_REPEATS} repeats per fixture on identical input",
        )
    )
    report.results.append(
        MetricResult(
            BY_KEY["latency_p95_seconds"],
            percentile([s["seconds"] for s in scans], 95),
            detail=f"{len(scans)} fixture scans, no network — a live crawl adds ~44s of throttle",
        )
    )
    report.results.append(
        MetricResult(
            BY_KEY["cost_per_scan_usd"],
            router.usage.cost_usd,
            detail=f"{router.usage.calls} model call(s) via {router.usage.by_provider or 'none'}",
        )
    )

    report.notes.append(
        "Scans run against saved HTML fixtures, not live sites: the crawler refuses to "
        "start until WASL_CRAWLER_INFO_URL and WASL_OPT_OUT_EMAIL point at a live page "
        "and a real mailbox. Every model call, validator and critic rule is the "
        "production one; only the network is skipped."
    )
    if blocked_reason:
        report.notes.append(
            "Capability precision/recall and band accuracy are BLOCKED. They need "
            "seeds/golden/labels.yaml filled in by hand — the system must never generate "
            "its own ground truth, or the eval is circular."
        )

    return report


def render(report: EvalReport) -> str:
    lines = [
        "WASL AI — EVALUATION REPORT",
        f"Golden set: {report.golden_set_size} sites ({report.golden_labelled} labelled) · "
        f"Model: {report.model} · {report.run_date}",
        "",
    ]

    for metric_class, heading in (
        (MetricClass.GATE, "GATES  (binary — a failure blocks the build)"),
        (MetricClass.TUNING, "TUNING"),
        (MetricClass.OPERATING, "OPERATING"),
    ):
        lines.append(heading)
        for result in report.of_class(metric_class):
            lines.append(
                f"  {result.spec.key:<32} {result.value_text:>7}   "
                f"[{result.spec.target_text():<5}]  {result.status.value}"
            )
            if result.status is Status.BLOCKED and result.blocked_reason:
                lines.append(f"      blocked: {result.blocked_reason}")
            elif result.detail:
                lines.append(f"      {result.detail}")
        lines.append("")

    if report.failures:
        lines.append(f"FAILURES ({len(report.failures)})")
        lines.extend(f"  - {failure}" for failure in report.failures)
        lines.append("")

    thin = report.thin
    if thin:
        lines.append(f"THIN ({len(thin)}) — computed, but over too few samples to be a claim")
        lines.extend(
            f"  - {r.spec.key}: {r.value_text} over {r.samples} sample(s)" for r in thin
        )
        lines.append("")

    blocked = report.blocked
    if blocked:
        lines.append(f"BLOCKED ({len(blocked)}) — not estimated, not guessed")
        lines.extend(f"  - {r.spec.key}" for r in blocked)
        lines.append("")

    for note in report.notes:
        lines.append(f"NOTE  {note}")
    if report.notes:
        lines.append("")

    lines.append(f"prompts: {', '.join(f'{k}@{v}' for k, v in report.prompt_shas.items())}")
    lines.append("")
    return "\n".join(lines)


def render_markdown(report: EvalReport) -> str:
    """The README table — the artifact people actually read."""
    lines = [
        f"_Golden set: {report.golden_set_size} sites ({report.golden_labelled} hand-labelled) · "
        f"model `{report.model}` · run {report.run_date}._",
        "",
        "| Metric | Class | Result | Target | Status |",
        "|---|---|---:|---:|---|",
    ]
    for result in report.results:
        status = result.status.value
        badge = {
            "PASS": "✅ PASS",
            "FAIL": "❌ FAIL",
            "BELOW": "⚠️ BELOW",
            "BLOCKED": "⏸ BLOCKED",
            "THIN": "🔍 THIN",
        }[status]
        lines.append(
            f"| {result.spec.label} | {result.spec.metric_class.value} | "
            f"`{result.value_text}` | `{result.spec.target_text()}` | {badge} |"
        )

    lines.append("")
    if report.thin:
        lines.append(
            "**🔍 THIN** means the metric was computed but over fewer than "
            f"{MIN_SAMPLES_FOR_A_CLAIM} samples. A figure on a denominator that small is not "
            "an accuracy claim, so it is not reported as passing."
        )
        lines.append("")
    if report.blocked:
        lines.append(
            "**Blocked metrics are not estimated.** "
            + ", ".join(f"`{r.spec.key}`" for r in report.blocked)
            + " require hand-labelled ground truth in `seeds/golden/labels.yaml`. "
            "The system must never generate its own labels — that would make the "
            "evaluation circular and every number above meaningless."
        )
        lines.append("")
    for note in report.notes:
        lines.append(f"> {note}")
        lines.append("")
    return "\n".join(lines)


def write_readme(report: EvalReport, path: Path = README_PATH) -> bool:
    """Replace the README's eval section between its markers."""
    if not path.exists():
        return False
    text = path.read_text()
    pattern = re.compile(
        r"(<!-- EVAL_TABLE_START -->)(.*?)(<!-- EVAL_TABLE_END -->)", re.DOTALL
    )
    if not pattern.search(text):
        return False
    path.write_text(pattern.sub(lambda m: f"{m.group(1)}\n{render_markdown(report)}\n{m.group(3)}", text))
    return True


async def main_async(args: argparse.Namespace) -> int:
    report = await build_report()
    print(render(report))

    if not args.no_readme:
        written = write_readme(report)
        print(f"README: {'updated' if written else 'markers not found, not updated'}")

    failures_dir = repo_root() / "services" / "api" / "eval" / "failures" / report.run_date
    if report.failures:
        failures_dir.mkdir(parents=True, exist_ok=True)
        (failures_dir / "failures.json").write_text(json.dumps(report.failures, indent=2))
        print(f"failures written to {failures_dir}")

    if not report.gates_pass:
        print("\nGATE FAILURE — build blocked.")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-readme", action="store_true", help="print only, do not edit README")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)-5s %(name)s: %(message)s",
    )
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
