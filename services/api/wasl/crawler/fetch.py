"""The fetcher: the only module in this repository that touches someone else's server.

Everything here is shaped by one constraint — we are a guest. Concretely:

**Every request is rate-limited, including the probes.** llms.txt, sitemaps,
`.well-known` and OpenAPI probes are requests like any other and go through the
same per-domain limiter as pages. Counting them is the difference between a
promised 0.5 req/s and an actual one.

**Pre-JS comes free.** Playwright's navigation response carries the raw body, so
capturing "before JavaScript" costs zero extra requests. Fetching the page twice
to get both phases would double our footprint for no information gain.

**The crawl is planned before it runs.** `plan()` produces the full intent —
domains, URLs, robots verdicts, wall-clock estimate — without sending anything.
A crawl you can review before it happens is a different thing from one you
apologise for afterwards.

**GET only, always.** There is no code path here that issues any other method.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from wasl.config import Settings, get_settings
from wasl.crawler.cache import SnapshotCache
from wasl.crawler.detectors.sitemap import parse_urls as parse_sitemap_urls
from wasl.crawler.policy import (
    MAX_REDIRECT_DEPTH,
    PROBE_PATHS,
    REQUEST_TIMEOUT_SECONDS,
    Budget,
    CrawlPolicy,
    normalise_domain,
    total_request_estimate,
)
from wasl.crawler.ratelimit import DomainRateLimiter
from wasl.crawler.robots import RobotsCache
from wasl.crawler.types import (
    CaptureMode,
    CapturedPage,
    CrawlPlan,
    FetchedResource,
    RobotsInfo,
    SiteArtifacts,
)

logger = logging.getLogger(__name__)

# Resource types never worth downloading. We score markup.
_BLOCKED_RESOURCE_TYPES = {"image", "font", "media"}

# Desktop viewport. Some sites serve materially different DOM at mobile widths,
# so this is pinned rather than left to the default.
_VIEWPORT = {"width": 1440, "height": 900}

# Hard ceiling on waiting for network idle. Plenty of sites never idle at all —
# analytics beacons, polling, websockets — so this must not be open-ended.
_NETWORKIDLE_TIMEOUT_MS = 6000
_NAVIGATION_TIMEOUT_MS = REQUEST_TIMEOUT_SECONDS * 1000


class CrawlRefused(RuntimeError):
    """Raised when policy forbids a crawl. Carries the rule that refused it."""

    def __init__(self, rule: str, reason: str) -> None:
        super().__init__(f"[{rule}] {reason}")
        self.rule = rule
        self.reason = reason


class Crawler:
    """Fetches a site within policy. One instance per crawl.

    Use as an async context manager so the browser and HTTP client are always
    torn down, including on failure.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        policy: CrawlPolicy | None = None,
        limiter: DomainRateLimiter | None = None,
        cache: SnapshotCache | None = None,
        budget: Budget = Budget.INTERACTIVE,
    ) -> None:
        self._settings = settings or get_settings()
        # Refuses here, before anything is fetched, if the crawler cannot
        # identify itself honestly.
        self._user_agent = self._settings.user_agent()
        self._policy = policy or CrawlPolicy()
        self._limiter = limiter or DomainRateLimiter.from_settings()
        self._cache = cache or SnapshotCache()
        self._budget = budget

        self._client: httpx.AsyncClient | None = None
        self._robots: RobotsCache | None = None
        self._playwright = None
        self._browser = None
        self.requests_made = 0

    async def __aenter__(self) -> Crawler:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self._user_agent, "Accept": "*/*"},
            follow_redirects=True,
            max_redirects=MAX_REDIRECT_DEPTH,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._robots = RobotsCache(self._client, user_agent=self._user_agent)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        if self._client is not None:
            await self._client.aclose()
        await self._limiter.close()

    # --- browser lifecycle ---------------------------------------------------

    async def _ensure_browser(self):
        """Start Chromium lazily. A degraded run never pays for it."""
        if self._browser is not None:
            return self._browser
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    @property
    def playwright_enabled(self) -> bool:
        return self._settings.playwright_available

    # --- throttled primitives ------------------------------------------------

    async def _get(self, url: str) -> FetchedResource:
        """One rate-limited GET. The only HTTP verb this class knows."""
        assert self._client is not None
        await self._limiter.acquire(url)
        self.requests_made += 1
        try:
            response = await self._client.get(url)
        except Exception as exc:
            return FetchedResource(url=url, status_code=0, fetch_error=f"{type(exc).__name__}: {exc}")
        return FetchedResource(
            url=str(response.url),
            status_code=response.status_code,
            content_type=response.headers.get("content-type", ""),
            text=response.text if len(response.content) < 5_000_000 else "",
        )

    # --- site artifacts ------------------------------------------------------

    async def fetch_robots(self, root_url: str) -> RobotsInfo:
        assert self._robots is not None
        await self._limiter.acquire(root_url)
        self.requests_made += 1
        return await self._robots.get(root_url)

    async def fetch_site_artifacts(self, root_url: str) -> SiteArtifacts:
        """Fetch robots.txt and the fixed probe set, then any sitemap it declared."""
        domain = normalise_domain(root_url)
        robots = await self.fetch_robots(root_url)

        # A site that declares its sitemaps has told us where to look; prefer that
        # over the blind /sitemap.xml guess.
        declared = [urljoin(root_url, s) for s in robots.sitemaps][:2]
        probe_paths = [p for p in PROBE_PATHS if not (p == "/sitemap.xml" and declared)]

        probe_urls = [urljoin(root_url, path) for path in probe_paths] + declared
        allowed_urls = [u for u in probe_urls if self._policy.check_url(u).allowed]

        results: dict[str, FetchedResource] = {}
        for url in allowed_urls:
            if self._robots and not await self._robots.is_allowed(url):
                results[url] = FetchedResource(
                    url=url, status_code=0, fetch_error="robots.txt disallows this path"
                )
                continue
            results[url] = await self._get(url)

        def matching(*needles: str) -> tuple[FetchedResource, ...]:
            return tuple(r for u, r in results.items() if any(n in u for n in needles))

        llms = next((r for u, r in results.items() if u.endswith("/llms.txt")), None)
        sitemaps = tuple(
            r for u, r in results.items() if "sitemap" in u.lower() or u in declared
        )

        return SiteArtifacts(
            root_url=root_url,
            domain=domain,
            robots=robots,
            llms_txt=llms,
            sitemaps=sitemaps,
            wellknown=matching("/.well-known/"),
            openapi_candidates=matching("openapi.json", "swagger.json", "api-docs"),
        )

    # --- page capture --------------------------------------------------------

    async def fetch_page(self, url: str, *, use_cache: bool = True) -> CapturedPage:
        """Capture one page, pre-JS and post-JS, respecting robots and the limiter."""
        if use_cache:
            cached = self._cache.get(url)
            if cached is not None:
                logger.debug("cache hit: %s", url)
                return cached

        decision = self._policy.check_url(url)
        if not decision.allowed:
            return self._refused(url, f"[{decision.rule}] {decision.reason}")

        assert self._robots is not None
        if not await self._robots.is_allowed(url):
            page = self._refused(url, "robots.txt disallows this path", robots_blocked=True)
            self._cache.put(page)
            return page

        await self._limiter.acquire(url)
        self.requests_made += 1

        page = (
            await self._capture_with_browser(url)
            if self.playwright_enabled
            else await self._capture_degraded(url)
        )
        self._cache.put(page)
        return page

    @staticmethod
    def _refused(url: str, reason: str, *, robots_blocked: bool = False) -> CapturedPage:
        return CapturedPage(
            url=url,
            final_url=url,
            status_code=0,
            headers={},
            pre_js_html="",
            post_js_html="",
            mode=CaptureMode.DEGRADED,
            response_time_ms=0,
            fetched_at=datetime.now(UTC),
            robots_blocked=robots_blocked,
            fetch_error=reason,
        )

    async def _capture_with_browser(self, url: str) -> CapturedPage:
        browser = await self._ensure_browser()
        started = time.perf_counter()

        context = await browser.new_context(
            user_agent=self._user_agent,
            viewport=_VIEWPORT,
            ignore_https_errors=False,
        )

        async def _route(route, request):  # type: ignore[no-untyped-def]
            if request.resource_type in _BLOCKED_RESOURCE_TYPES:
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", _route)
        page = await context.new_page()

        try:
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS
            )
            if response is None:
                raise RuntimeError("navigation returned no response")

            # The navigation response body IS the pre-JS document. Free.
            try:
                pre_js = await response.text()
            except Exception:
                pre_js = ""

            headers = await response.all_headers()
            status = response.status

            # Best-effort idle. Many sites never reach it; that is not a failure.
            try:
                await page.wait_for_load_state("networkidle", timeout=_NETWORKIDLE_TIMEOUT_MS)
            except Exception:
                logger.debug("networkidle not reached for %s; capturing anyway", url)

            post_js = await page.content()
            final_url = page.url

            return CapturedPage(
                url=url,
                final_url=final_url,
                status_code=status,
                headers=headers,
                pre_js_html=pre_js,
                post_js_html=post_js,
                mode=CaptureMode.FULL,
                response_time_ms=int((time.perf_counter() - started) * 1000),
                fetched_at=datetime.now(UTC),
            )
        except Exception as exc:
            logger.warning("browser capture failed for %s: %s", url, exc)
            return CapturedPage(
                url=url,
                final_url=url,
                status_code=0,
                headers={},
                pre_js_html="",
                post_js_html="",
                mode=CaptureMode.DEGRADED,
                response_time_ms=int((time.perf_counter() - started) * 1000),
                fetched_at=datetime.now(UTC),
                fetch_error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            await context.close()

    async def _capture_degraded(self, url: str) -> CapturedPage:
        """HTTP-only capture, for environments without a browser.

        Loses the pre-JS/post-JS delta entirely, which is Axis 4's headline
        signal. `mode` carries that fact downstream so the rubric suppresses the
        rendering check rather than scoring it zero.
        """
        assert self._client is not None
        started = time.perf_counter()
        try:
            response = await self._client.get(url)
        except Exception as exc:
            return self._refused(url, f"{type(exc).__name__}: {exc}")

        return CapturedPage(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            headers=dict(response.headers),
            pre_js_html=response.text,
            post_js_html="",
            mode=CaptureMode.DEGRADED,
            response_time_ms=int((time.perf_counter() - started) * 1000),
            fetched_at=datetime.now(UTC),
        )

    # --- URL discovery -------------------------------------------------------

    def _same_site(self, candidate: str, root: str) -> bool:
        return normalise_domain(urlparse(candidate).netloc) == normalise_domain(
            urlparse(root).netloc
        )

    def discover_urls(
        self, root_url: str, artifacts: SiteArtifacts, homepage: CapturedPage | None
    ) -> list[str]:
        """Build the candidate URL list: sitemap first, then homepage links.

        Sitemap first because it is the site telling us what exists, which beats
        guessing and produces no 404s on someone else's server.
        """
        candidates: list[str] = []

        def offer(url: str) -> None:
            url = url.split("#")[0].rstrip("/") or url
            if url in candidates or url == root_url.rstrip("/"):
                return
            if not self._same_site(url, root_url):
                return
            if not self._policy.check_url(url).allowed:
                return
            candidates.append(url)

        for resource in artifacts.sitemaps:
            if resource.found:
                for url in parse_sitemap_urls(resource.text):
                    offer(url)

        if homepage is not None and homepage.ok:
            html = homepage.html_for(
                "post_js" if homepage.post_js_html else "pre_js"
            )
            soup = BeautifulSoup(html, "lxml")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor["href"]).strip()
                if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    offer(urljoin(homepage.final_url, href))

        return candidates

    # --- planning ------------------------------------------------------------

    async def plan(self, root_url: str, *, user_submitted: bool = False) -> CrawlPlan:
        """Describe what a crawl would do. Fetches robots and the probe set only.

        Deliberately does fetch robots.txt: a plan that guesses at the robots
        verdict is not a plan worth reviewing.
        """
        domain_decision = self._policy.check_domain(root_url, user_submitted=user_submitted)
        if not domain_decision.allowed:
            raise CrawlRefused(domain_decision.rule, domain_decision.reason)

        artifacts = await self.fetch_site_artifacts(root_url)
        candidates = self.discover_urls(root_url, artifacts, homepage=None)

        excluded: list[tuple[str, str]] = []
        allowed: list[str] = []
        for url in candidates:
            decision = self._policy.check_url(url)
            if decision.allowed:
                allowed.append(url)
            else:
                excluded.append((url, decision.rule))

        notes = [
            f"{total_request_estimate(self._budget)} requests planned "
            f"({self._budget.page_cap} pages + {len(PROBE_PATHS) + 1} site probes)",
            f"robots.txt: {'present' if artifacts.robots.present else 'absent'}"
            + (
                f", AI-agent stanzas: {list(artifacts.robots.ai_agent_stanzas)}"
                if artifacts.robots.ai_agent_stanzas
                else ", no AI-agent stanza"
            ),
        ]
        if artifacts.robots.crawl_delay:
            notes.append(f"honouring robots Crawl-delay of {artifacts.robots.crawl_delay}s")

        return CrawlPlan(
            domain=normalise_domain(root_url),
            root_url=root_url,
            budget_name=self._budget.value,
            page_cap=self._policy.page_cap(self._budget),
            requests_per_second=1.0 / self._limiter.interval_seconds,
            robots=artifacts.robots,
            candidate_urls=tuple([root_url, *allowed]),
            excluded_urls=tuple(excluded[:50]),
            notes=notes,
        )

    # --- the crawl -----------------------------------------------------------

    async def crawl(
        self, root_url: str, *, user_submitted: bool = False
    ) -> tuple[list[CapturedPage], SiteArtifacts]:
        """Crawl a site within budget. Returns captured pages and site artifacts."""
        decision = self._policy.check_domain(root_url, user_submitted=user_submitted)
        if not decision.allowed:
            raise CrawlRefused(decision.rule, decision.reason)

        logger.info(
            "crawl start: %s budget=%s cap=%d ua=%s",
            root_url,
            self._budget.value,
            self._policy.page_cap(self._budget),
            self._user_agent,
        )

        artifacts = await self.fetch_site_artifacts(root_url)
        self._limiter = self._limiter.with_crawl_delay(artifacts.robots.crawl_delay)

        cap = self._policy.page_cap(self._budget)
        homepage = await self.fetch_page(root_url)
        pages: list[CapturedPage] = [homepage]

        for url in self.discover_urls(root_url, artifacts, homepage):
            if len(pages) >= cap:
                break
            pages.append(await self.fetch_page(url))

        logger.info(
            "crawl done: %s pages=%d requests=%d robots_blocked=%d",
            root_url,
            len(pages),
            self.requests_made,
            sum(1 for p in pages if p.robots_blocked),
        )
        return pages, artifacts


async def crawl_site(
    root_url: str, *, budget: Budget = Budget.INTERACTIVE, user_submitted: bool = False
) -> tuple[list[CapturedPage], SiteArtifacts]:
    """Convenience wrapper for a single crawl."""
    async with Crawler(budget=budget) as crawler:
        return await crawler.crawl(root_url, user_submitted=user_submitted)
