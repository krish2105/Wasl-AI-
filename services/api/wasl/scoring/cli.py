"""Score a site from fixtures or from a cached crawl, and print the six-axis table.

    uv run python -m wasl.scoring.cli --fixture rich_site
    uv run python -m wasl.scoring.cli --fixture thin_site --fixture spa_site
    uv run python -m wasl.scoring.cli --url https://example.com   # from cache

The fixture mode exists so the rubric can be demonstrated and reviewed without
touching the network at all. Every number it prints is reproducible by anyone who
clones the repository, which is a stronger claim than a screenshot of a live run.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from wasl.crawler.cache import SnapshotCache
from wasl.crawler.detectors import extract_all
from wasl.crawler.robots import parse_robots
from wasl.crawler.types import CaptureMode, CapturedPage, FetchedResource, SiteArtifacts
from wasl.scoring.rubric import format_report, score_site, scoring_input_from_crawl

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"

# A neutral site-level context for fixture scoring: robots present and open, no
# llms.txt, no sitemap. Anything a fixture is meant to demonstrate has to come
# from its own markup rather than from a favourable environment.
NEUTRAL_ROBOTS = "User-agent: *\nDisallow: /admin\n"


def load_fixture(name: str, *, url: str | None = None) -> CapturedPage:
    pre_path = FIXTURES / f"{name}.pre.html"
    if not pre_path.exists():
        pre_path = FIXTURES / f"{name}.html"
    post_path = FIXTURES / f"{name}.post.html"

    if not pre_path.exists():
        raise SystemExit(
            f"No fixture named {name!r} in {FIXTURES}. "
            f"Available: {sorted(p.name for p in FIXTURES.glob('*.html'))}"
        )

    pre = pre_path.read_text()
    post = post_path.read_text() if post_path.exists() else ""

    return CapturedPage(
        url=url or f"https://{name.replace('_', '-')}.example/",
        final_url=url or f"https://{name.replace('_', '-')}.example/",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        pre_js_html=pre,
        post_js_html=post,
        mode=CaptureMode.FULL if post else CaptureMode.DEGRADED,
        response_time_ms=100,
        fetched_at=datetime.now(UTC),
    )


def neutral_artifacts(root_url: str) -> SiteArtifacts:
    from urllib.parse import urlparse

    return SiteArtifacts(
        root_url=root_url,
        domain=urlparse(root_url).netloc,
        robots=parse_robots(NEUTRAL_ROBOTS, url=f"{root_url.rstrip('/')}/robots.txt"),
        llms_txt=FetchedResource(url=f"{root_url.rstrip('/')}/llms.txt", status_code=404),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="append", default=[], help="fixture name (repeatable)")
    parser.add_argument("--url", help="score the most recent cached crawl of this URL")
    parser.add_argument("--quiet", action="store_true", help="one summary line per site")
    args = parser.parse_args()

    if not args.fixture and not args.url:
        parser.error("give --fixture NAME or --url URL")

    targets: list[tuple[str, list[CapturedPage], SiteArtifacts]] = []

    for name in args.fixture:
        page = load_fixture(name)
        targets.append((name, [page], neutral_artifacts(page.final_url)))

    if args.url:
        cached = SnapshotCache().latest(args.url)
        if cached is None:
            raise SystemExit(f"No cached snapshot for {args.url}. Run a crawl first.")
        targets.append((args.url, [cached], neutral_artifacts(args.url)))

    for label, pages, artifacts in targets:
        store = extract_all(pages, artifacts)
        score = score_site(store, scoring_input_from_crawl(store, pages))

        if args.quiet:
            band = score.band or "SUPPRESSED"
            print(
                f"{label:<24} {score.total:>3}/{score.max_possible:<3} "
                f"{band:<14} {score.confidence.value:<5} "
                f"evidence={len(store)}"
            )
        else:
            print(format_report(score, domain=label))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
