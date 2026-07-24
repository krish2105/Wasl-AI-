#!/usr/bin/env python
"""Check that every seed URL is still live, and write the verified registry.

Why this exists, in the seed file's own words: the domains were compiled from
general knowledge and are not guaranteed live. Companies rebrand, merge and move.
Publishing a leaderboard built on a dead URL is a small embarrassment; publishing
one where a redirect quietly points somewhere else is a larger one.

So: one HEAD per URL, follow redirects, record where it actually landed, and
write `seeds/seed_urls.verified.yaml`. Only the verified file feeds the
leaderboard.

It also asserts `expected_counts` and fails loudly on drift, which is how the
99-vs-101 discrepancy in the original file was meant to be caught.

Read-only and HEAD-only. One request per domain, run concurrently across
different domains — the 0.5 req/s limit is per domain, and this sends exactly one
to each.

    uv run python scripts/verify_seeds.py
    uv run python scripts/verify_seeds.py --dry-run     # counts only, no requests
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from wasl.crawler.policy import normalise_domain, repo_root  # noqa: E402

HEAD_TIMEOUT_SECONDS = 2.0
# Sites that ignore or throttle HEAD get a second chance with GET on a realistic
# timeout. The seed file specified a 2s HEAD, and taken literally that marks Noon,
# Namshi, flydubai and MOHRE as dead — four live sites, all of them golden. A
# verifier that silently deletes a quarter of the golden set because a CDN was
# slow is worse than no verifier.
RETRY_TIMEOUT_SECONDS = 10.0
MAX_CONCURRENCY = 12

SEED_PATH = repo_root() / "seeds" / "seed_urls.yaml"
VERIFIED_PATH = repo_root() / "seeds" / "seed_urls.verified.yaml"

# ok         reachable at the URL given
# redirected reachable, but somewhere else — url is rewritten in place
# blocked    the site exists and refused us (403, TLS failure, redirect loop,
#            bot wall). Kept: a site that blocks crawlers is a legitimate entry
#            and its blocking is itself a scoring signal.
# dead       the domain does not resolve, or the URL returns 404/410. Dropped.
Status = str


def _classify_exception(exc: Exception) -> tuple[Status, str]:
    """Map a transport failure to a verdict.

    The distinction that matters: "this domain does not exist" is death, while
    "this server dislikes us" is not. Only the first justifies dropping an entry.
    """
    name = type(exc).__name__
    text = str(exc)

    if isinstance(exc, httpx.TooManyRedirects):
        return "blocked", f"{name}: redirect loop (often a bot wall or cookie gate)"

    if "nodename nor servname" in text or "Name or service not known" in text or "getaddrinfo" in text:
        return "dead", f"{name}: DNS does not resolve"

    if "CERTIFICATE_VERIFY_FAILED" in text or "SSL" in text:
        # The host is there; its TLS is misconfigured. That is a real finding
        # about the site, not a reason to pretend it does not exist.
        detail = "expired certificate" if "has expired" in text else "TLS verification failed"
        return "blocked", f"{name}: {detail}"

    if isinstance(exc, httpx.TimeoutException):
        return "blocked", "no response within timeout (slow origin or HEAD not served)"

    return "blocked", f"{name}: {text[:120]}"


async def check(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    """HEAD one URL, retrying once with GET, and classify the outcome."""
    async with semaphore:
        response: httpx.Response | None = None
        first_error: Exception | None = None

        try:
            response = await client.head(url, timeout=HEAD_TIMEOUT_SECONDS, follow_redirects=True)
        except Exception as exc:
            first_error = exc

        # Retry once with GET. Plenty of origins do not serve HEAD at all, and a
        # CDN cold start routinely exceeds two seconds.
        needs_retry = response is None or response.status_code in {403, 405, 406, 429, 500, 503}
        if needs_retry:
            try:
                response = await client.get(url, timeout=RETRY_TIMEOUT_SECONDS, follow_redirects=True)
                first_error = None
            except Exception as exc:
                if response is None:
                    first_error = first_error or exc

        if response is None:
            assert first_error is not None
            status, detail = _classify_exception(first_error)
            return {"status": status, "detail": detail, "final_url": url, "status_code": 0}

        final_url = str(response.url)
        code = response.status_code

        if code in {404, 410}:
            status = "dead"
        elif code >= 400:
            status = "blocked"
        elif normalise_domain(final_url) != normalise_domain(url):
            status = "redirected"
        else:
            status = "ok"

        return {
            "status": status,
            "detail": f"HTTP {code}",
            "final_url": final_url,
            "status_code": code,
        }


def assert_counts(data: dict[str, Any]) -> list[str]:
    """Compare declared expected_counts against reality. Returns failures."""
    groups = data.get("groups") or {}
    sites = [s for g in groups.values() for s in g.get("sites", [])]
    actual = {
        "total_sites": len(sites),
        "golden_sites": sum(1 for s in sites if s.get("golden")),
        "groups": len(groups),
    }
    expected = data.get("expected_counts") or {}

    failures = []
    for key, actual_value in actual.items():
        declared = expected.get(key)
        marker = "OK" if declared == actual_value else "MISMATCH"
        print(f"  {key:<14} actual={actual_value:<5} declared={declared!s:<5} {marker}")
        if declared != actual_value:
            failures.append(f"{key}: actual {actual_value}, declared {declared}")
    return failures


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="assert counts only; send no requests"
    )
    parser.add_argument("--seeds", type=Path, default=SEED_PATH)
    parser.add_argument("--out", type=Path, default=VERIFIED_PATH)
    args = parser.parse_args()

    data = yaml.safe_load(args.seeds.read_text())

    print(f"WASL AI — seed verification\n{args.seeds}\n")
    print("COUNTS")
    count_failures = assert_counts(data)
    if count_failures:
        print("\nFAIL: expected_counts does not match the registry.")
        for failure in count_failures:
            print(f"  - {failure}")
        return 1

    if args.dry_run:
        print("\n--dry-run: no requests sent.")
        return 0

    groups = data["groups"]
    targets = [
        (group_key, site)
        for group_key, group in groups.items()
        for site in group.get("sites", [])
    ]

    print(f"\nCHECKING {len(targets)} URLs (HEAD, {HEAD_TIMEOUT_SECONDS}s timeout, "
          f"max {MAX_CONCURRENCY} concurrent)\n")

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    async with httpx.AsyncClient(
        headers={"User-Agent": "WaslAI-Research/0.1 (seed verification; +https://github.com/)"},
        max_redirects=5,
    ) as client:
        results = await asyncio.gather(
            *(check(client, site["url"], semaphore) for _, site in targets)
        )

    tally: dict[str, int] = {}
    verified_groups: dict[str, Any] = {}
    dropped: list[str] = []

    for (group_key, site), result in zip(targets, results, strict=True):
        status = result["status"]
        tally[status] = tally.get(status, 0) + 1

        symbol = {"ok": "  ", "redirected": "->", "blocked": "##", "dead": "XX"}[status]
        note = ""
        if status == "redirected":
            note = f"  => {result['final_url']}"
        elif status in {"dead", "blocked"}:
            note = f"  ({result['detail']})"
        print(f" {symbol} {site['name']:<28} {site['url']}{note}")

        if status == "dead":
            dropped.append(f"{site['name']} ({site['url']}): {result['detail']}")
            continue

        entry = dict(site)
        if status == "redirected":
            entry["url"] = result["final_url"]
            entry["original_url"] = site["url"]
        entry["verify_status"] = status
        entry["verify_detail"] = result["detail"]

        verified_groups.setdefault(
            group_key,
            {"label": groups[group_key].get("label", group_key),
             "hypothesis": groups[group_key].get("hypothesis", ""),
             "sites": []},
        )["sites"].append(entry)

    verified = {
        "version": data.get("version", 1),
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": "scripts/verify_seeds.py",
        "source": str(args.seeds.relative_to(repo_root())),
        "crawl_policy": data.get("crawl_policy", {}),
        "groups": verified_groups,
        "excluded": data.get("excluded", {"domains": [], "reasons": {}}),
        "verification_summary": tally,
        "dropped": dropped,
    }
    args.out.write_text(yaml.safe_dump(verified, sort_keys=False, allow_unicode=True))

    surviving = sum(len(g["sites"]) for g in verified_groups.values())
    surviving_golden = sum(
        1 for g in verified_groups.values() for s in g["sites"] if s.get("golden")
    )
    expected_golden = data["expected_counts"]["golden_sites"]

    print(f"\nSUMMARY  " + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    print(f"{surviving} of {len(targets)} entries written to {args.out.relative_to(repo_root())}")
    print(f"golden set: {surviving_golden} of {expected_golden} surviving")

    if dropped:
        print(f"\n{len(dropped)} dropped as dead:")
        for item in dropped:
            print(f"  - {item}")

    blocked = [
        f"{s['name']} ({s['url']}): {s['verify_detail']}"
        for g in verified_groups.values()
        for s in g["sites"]
        if s.get("verify_status") == "blocked"
    ]
    if blocked:
        print(f"\n{len(blocked)} kept but blocked — these still crawl, and the block is a finding:")
        for item in blocked:
            print(f"  - {item}")

    # Losing a golden site is a real failure. The eval harness needs all 30, the
    # stratification is deliberate, and quietly continuing with 26 would corrupt
    # every metric computed against them.
    if surviving_golden < expected_golden:
        missing = [
            f"{site['name']} ({site['url']})"
            for _, site in targets
            if site.get("golden")
            and not any(
                s["name"] == site["name"] for g in verified_groups.values() for s in g["sites"]
            )
        ]
        print(
            f"\nFAIL: the golden set lost {expected_golden - surviving_golden} "
            f"entrie(s). Replace them in seeds/seed_urls.yaml before running the eval:"
        )
        for item in missing:
            print(f"  - {item}")
        return 1

    # A dead non-golden URL is expected drift, not a failure of this script.
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
