"""Shared crawler data types.

Kept in their own module, free of heavy imports, so the detector layer can depend
on the *shape* of a captured page without importing Playwright. Detectors are
pure functions and their tests should not need a browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

Phase = Literal["pre_js", "post_js"]


class CaptureMode(StrEnum):
    """How a page was fetched.

    FULL means Playwright ran and both the raw response body and the hydrated DOM
    were captured. DEGRADED means only an HTTP fetch was possible — which loses
    the pre-JS/post-JS delta, Axis 4's headline signal. The distinction is carried
    all the way through to the report, because "we could not look" and "we looked
    and found nothing" are different claims and must not score the same.
    """

    FULL = "full"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class RobotsInfo:
    """What robots.txt said, as data.

    `agent_stanzas` is the interesting field: an explicit stanza naming an AI
    crawler — whether it allows or disallows — signals that someone thought about
    agent access. Silence does not. Axis 1 scores the clarity, not the verdict.
    """

    url: str
    present: bool
    parseable: bool
    raw: str = ""
    sitemaps: tuple[str, ...] = ()
    agent_stanzas: tuple[str, ...] = ()
    ai_agent_stanzas: tuple[str, ...] = ()
    crawl_delay: float | None = None
    fetch_error: str | None = None


@dataclass(frozen=True, slots=True)
class CapturedPage:
    """One fetched URL, captured before and after JavaScript.

    `pre_js_html` is the raw HTTP response body. `post_js_html` is the DOM after
    hydration and network idle. On a DEGRADED capture, `post_js_html` is empty
    and every consumer must check `mode` rather than assuming.
    """

    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    pre_js_html: str
    post_js_html: str
    mode: CaptureMode
    response_time_ms: int
    fetched_at: datetime
    robots_blocked: bool = False
    fetch_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.fetch_error is None and 200 <= self.status_code < 300

    @property
    def redirected(self) -> bool:
        return self.final_url != self.url

    def html_for(self, phase: Phase) -> str:
        """The markup for a phase. Empty string when that phase was not captured."""
        return self.pre_js_html if phase == "pre_js" else self.post_js_html

    @property
    def available_phases(self) -> tuple[Phase, ...]:
        """Which phases actually hold markup. Degraded captures have only pre_js."""
        phases: list[Phase] = []
        if self.pre_js_html:
            phases.append("pre_js")
        if self.post_js_html:
            phases.append("post_js")
        return tuple(phases)


@dataclass(frozen=True, slots=True)
class FetchedResource:
    """A site-level file we probed for: llms.txt, a sitemap, a .well-known entry.

    A 404 here is a result, not a failure — "this site has no llms.txt" is
    precisely what Axis 1 wants to know. So absence is recorded rather than
    raised.
    """

    url: str
    status_code: int
    content_type: str = ""
    text: str = ""
    fetch_error: str | None = None

    @property
    def found(self) -> bool:
        return self.fetch_error is None and 200 <= self.status_code < 300 and bool(self.text.strip())


@dataclass(frozen=True, slots=True)
class SiteArtifacts:
    """Everything fetched once per site rather than once per page.

    Separated from `CapturedPage` because these are origin-scoped: robots.txt and
    llms.txt live at the root and describe the whole site. Keeping them apart
    lets the site-level detectors stay pure functions over already-fetched
    content, with no I/O of their own.
    """

    root_url: str
    domain: str
    robots: RobotsInfo
    llms_txt: FetchedResource | None = None
    sitemaps: tuple[FetchedResource, ...] = ()
    wellknown: tuple[FetchedResource, ...] = ()
    openapi_candidates: tuple[FetchedResource, ...] = ()


@dataclass(frozen=True, slots=True)
class CrawlPlan:
    """What a crawl intends to do, before it does any of it.

    Produced by the dry-run path. Showing this — domain, page budget, robots
    decision, estimated wall-clock — before a single request goes out is what
    makes a crawl reviewable rather than merely polite.
    """

    domain: str
    root_url: str
    budget_name: str
    page_cap: int
    requests_per_second: float
    robots: RobotsInfo
    candidate_urls: tuple[str, ...] = ()
    excluded_urls: tuple[tuple[str, str], ...] = ()  # (url, reason)
    notes: list[str] = field(default_factory=list)

    @property
    def estimated_seconds(self) -> float:
        """Throttle floor. Real crawls take longer; none take less."""
        return min(len(self.candidate_urls), self.page_cap) / self.requests_per_second
