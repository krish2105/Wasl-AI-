"""Crawl node. Deterministic. No model.

Wraps the Phase 2 crawler and reduces its output into serialisable state. The
heavy HTML stays in the snapshot cache; only summaries and evidence travel
through the graph, so a checkpoint stays small enough that resuming is genuinely
cheaper than re-crawling.
"""

from __future__ import annotations

import logging

from wasl.config import ConfigurationError
from wasl.crawler.fetch import Crawler, CrawlRefused
from wasl.crawler.policy import Budget as CrawlBudget
from wasl.crawler.types import CaptureMode
from wasl.graph.state import PageSummary, WaslState
from wasl.obs.tracing import node_span

logger = logging.getLogger(__name__)


def summarise(page) -> PageSummary:
    return PageSummary(
        url=page.url,
        final_url=page.final_url,
        status_code=page.status_code,
        robots_blocked=page.robots_blocked,
        degraded=page.mode is CaptureMode.DEGRADED,
        pre_js_chars=len(page.pre_js_html),
        post_js_chars=len(page.post_js_html),
        fetch_error=page.fetch_error,
    )


async def crawl(state: WaslState) -> dict:
    """Fetch the site within policy, returning page summaries plus the raw capture.

    The captured pages are stashed on the returned dict under `_pages` for the
    extract node. They are not part of `WaslState` because they are large and
    already durable in the snapshot cache.
    """
    with node_span("crawl", job_id=state.job_id, domain=state.domain or state.root_url):
        if state.source == "fixture":
            # Replays a saved page from disk. This branch exists here rather than
            # in the caller because the graph is the execution path: a scan
            # resumed from a checkpoint has to reach the same decision the
            # original run did, and a caller-side branch would not survive the
            # round trip through Postgres.
            from wasl.scoring.cli import load_fixture, neutral_artifacts

            page = load_fixture(state.root_url)
            pages = [page]
            artifacts = neutral_artifacts(page.final_url)
        else:
            budget = CrawlBudget(state.budget_name)
            try:
                async with Crawler(budget=budget) as crawler:
                    pages, artifacts = await crawler.crawl(
                        state.root_url, user_submitted=state.user_submitted
                    )
            except CrawlRefused as exc:
                logger.warning("crawl refused: %s", exc)
                return {
                    "errors": [f"crawl refused [{exc.rule}]: {exc.reason}"],
                    "awaiting_confirmation": (
                        exc.rule if exc.rule == "not_allowlisted" else None
                    ),
                }
            except ConfigurationError as exc:
                # "the crawler is not configured to identify itself" is a
                # legitimate, expected state, not a crash. It must reach the UI
                # as a refusal with its reason intact.
                logger.warning("crawl unconfigured: %s", exc)
                return {"errors": [f"crawl refused [unconfigured]: {exc}"]}

        summaries = [summarise(page) for page in pages]
        logger.info(
            "crawl complete: %d pages, %d ok, %d robots-blocked",
            len(summaries),
            sum(1 for s in summaries if s.ok),
            sum(1 for s in summaries if s.robots_blocked),
        )

        return {
            "pages": summaries,
            "domain": artifacts.domain,
            "_pages": pages,
            "_artifacts": artifacts,
        }
