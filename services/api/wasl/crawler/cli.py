"""Command-line crawl: plan it, run it, print what was found.

    uv run python -m wasl.crawler.cli https://example.com --dry-run
    uv run python -m wasl.crawler.cli https://example.com

`--dry-run` is the important half. It fetches robots.txt and the probe set, then
prints the full intent — page budget, wall-clock estimate, robots verdict, which
URLs are in and which were refused and why — without touching a single page. A
crawl you can review before it happens is a different kind of thing from one you
explain afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter

from wasl.config import ConfigurationError
from wasl.crawler.detectors import extract_all
from wasl.crawler.evidence import EvidenceStore
from wasl.crawler.fetch import Crawler, CrawlRefused
from wasl.crawler.policy import Budget
from wasl.crawler.types import CaptureMode, CapturedPage, CrawlPlan, SiteArtifacts

RULE = "=" * 78
THIN = "-" * 78


def print_plan(plan: CrawlPlan) -> None:
    print(RULE)
    print(f"CRAWL PLAN  {plan.domain}")
    print(RULE)
    print(f"  root url         {plan.root_url}")
    print(f"  budget           {plan.budget_name} (cap {plan.page_cap} pages)")
    print(f"  rate             {plan.requests_per_second} req/s "
          f"({1 / plan.requests_per_second:.0f}s between requests)")
    print(f"  candidate urls   {len(plan.candidate_urls)}")
    print(f"  throttle floor   {plan.estimated_seconds:.0f}s for pages alone")
    for note in plan.notes:
        print(f"  note             {note}")

    print(f"\n  robots.txt: {plan.robots.url}")
    print(f"    present={plan.robots.present} parseable={plan.robots.parseable}")
    if plan.robots.fetch_error:
        print(f"    error: {plan.robots.fetch_error}")
    if plan.robots.agent_stanzas:
        print(f"    user-agents named: {list(plan.robots.agent_stanzas)[:8]}")
    print(f"    AI-agent stanzas: {list(plan.robots.ai_agent_stanzas) or 'none'}")
    if plan.robots.sitemaps:
        print(f"    sitemaps: {list(plan.robots.sitemaps)}")

    print(f"\n  WOULD FETCH ({min(len(plan.candidate_urls), plan.page_cap)} of "
          f"{len(plan.candidate_urls)}):")
    for url in plan.candidate_urls[: plan.page_cap]:
        print(f"    + {url}")
    if len(plan.candidate_urls) > plan.page_cap:
        print(f"    ... {len(plan.candidate_urls) - plan.page_cap} more, beyond the cap")

    if plan.excluded_urls:
        print(f"\n  REFUSED ({len(plan.excluded_urls)}):")
        by_rule = Counter(rule for _, rule in plan.excluded_urls)
        for rule, count in by_rule.most_common():
            example = next(u for u, r in plan.excluded_urls if r == rule)
            print(f"    - {rule}: {count}  e.g. {example}")
    print()


def print_pages(pages: list[CapturedPage]) -> None:
    print(RULE)
    print(f"PAGES  {len(pages)} fetched")
    print(RULE)
    print(f"  {'status':>6}  {'mode':<9} {'ms':>6}  {'pre':>7} {'post':>7}  url")
    print(f"  {THIN[:72]}")
    for page in pages:
        status = str(page.status_code) if page.status_code else "—"
        note = ""
        if page.robots_blocked:
            note = "  [robots-blocked]"
        elif page.fetch_error:
            note = f"  [{page.fetch_error[:44]}]"
        print(
            f"  {status:>6}  {page.mode.value:<9} {page.response_time_ms:>6}  "
            f"{len(page.pre_js_html):>7} {len(page.post_js_html):>7}  "
            f"{page.final_url[:52]}{note}"
        )

    ok = sum(1 for p in pages if p.ok)
    blocked = sum(1 for p in pages if p.robots_blocked)
    degraded = sum(1 for p in pages if p.mode is CaptureMode.DEGRADED)
    print(f"\n  {ok} ok · {blocked} robots-blocked · {degraded} degraded capture")
    if pages and blocked / len(pages) > 0.3:
        print("  NOTE: >30% robots-blocked — the rubric will suppress the grade band.")
    if ok < 8:
        print(f"  NOTE: only {ok} pages succeeded — below the 8-page confidence floor.")
    print()


def print_evidence(store: EvidenceStore, artifacts: SiteArtifacts) -> None:
    print(RULE)
    print(f"EVIDENCE  {len(store)} items")
    print(RULE)

    counts = store.kind_counts()
    width = max((len(k) for k in counts), default=10)
    for kind, count in counts.items():
        print(f"  {kind:<{width}}  {count:>4}")

    print(f"\n  {'id':<18} {'kind':<12} {'phase':<8} snippet")
    print(f"  {THIN[:72]}")
    for evidence in list(store)[:40]:
        print(f"  {evidence.id:<18} {evidence.kind:<12} {evidence.phase:<8} {evidence.short}")
    if len(store) > 40:
        print(f"  ... {len(store) - 40} more")

    dangling = store.verify_references([e.id for e in store])
    print(f"\n  referential integrity: {'OK' if not dangling else f'{len(dangling)} DANGLING'}")

    injections = [e for e in store.by_kind("injection") if "clean" not in (e.selector or "")]
    if injections:
        print(f"\n  INJECTION FINDINGS ({len(injections)}):")
        for evidence in injections[:10]:
            print(f"    - {evidence.selector}")
    print()


async def run(args: argparse.Namespace) -> int:
    budget = Budget(args.budget)
    try:
        async with Crawler(budget=budget) as crawler:
            if args.dry_run:
                print_plan(await crawler.plan(args.url, user_submitted=args.user_submitted))
                print("--dry-run: no pages were fetched.\n")
                return 0

            plan = await crawler.plan(args.url, user_submitted=args.user_submitted)
            print_plan(plan)

            pages, artifacts = await crawler.crawl(args.url, user_submitted=args.user_submitted)
            print_pages(pages)
            print_evidence(extract_all(pages, artifacts), artifacts)
            print(f"total requests issued: {crawler.requests_made}\n")
            return 0

    except ConfigurationError as exc:
        print(f"\nREFUSED TO CRAWL\n\n{exc}\n", file=sys.stderr)
        return 2
    except CrawlRefused as exc:
        print(f"\nREFUSED TO CRAWL\n\n  rule:   {exc.rule}\n  reason: {exc.reason}\n", file=sys.stderr)
        return 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="root URL to crawl (https only)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, fetch no pages")
    parser.add_argument("--budget", choices=[b.value for b in Budget], default=Budget.INTERACTIVE.value)
    parser.add_argument(
        "--user-submitted",
        action="store_true",
        help="treat as a runtime submission, bypassing the allowlist (never the exclusion list)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-5s %(name)s: %(message)s",
    )
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
