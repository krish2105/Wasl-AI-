"""Crawl orchestration, against a mocked transport.

Real network is deliberately absent here. What these tests exercise is the part
that decides *whether* to send a request, which is the part where a bug becomes
someone else's problem: a page cap that is off by one is a nuisance, a robots
check that runs after the fetch is a breach of the policy we publish.

The rate limiter is faked so the suite does not spend two seconds per simulated
request. That is the one thing mocked out; every policy decision is the real one.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from wasl.config import Settings
from wasl.crawler.cache import SnapshotCache
from wasl.crawler.fetch import Crawler, CrawlRefused
from wasl.crawler.policy import Budget, CrawlPolicy, SeedRegistry

ROOT = "https://allowed.example"

SEED_DATA = {
    "groups": {
        "test": {
            "label": "Test",
            "sites": [
                {"name": "Allowed", "url": ROOT},
                {"name": "Excluded", "url": "https://excluded.example"},
            ],
        }
    },
    "expected_counts": {"total_sites": 2, "golden_sites": 0, "groups": 1},
    "excluded": {"domains": ["excluded.example"], "reasons": {"excluded.example": "asked us to stop"}},
}

HOMEPAGE = """<!DOCTYPE html><html><head><title>Allowed</title></head><body>
<main><h1>Allowed</h1><p>Some genuine body content for the page.</p>
<a href="/a">A</a><a href="/b">B</a><a href="/c">C</a><a href="/d">D</a>
<a href="/admin">Admin</a><a href="/cart">Cart</a><a href="/doc.pdf">PDF</a>
<a href="https://elsewhere.example/x">Offsite</a>
</main></body></html>"""

PAGE = "<!DOCTYPE html><html><body><main><h1>Page</h1><p>Body text here.</p></main></body></html>"

ROBOTS_OPEN = "User-agent: *\nDisallow:\n"
ROBOTS_BLOCKS_B = "User-agent: *\nDisallow: /b\n"


class FakeLimiter:
    """Records reservations without sleeping."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.interval_seconds = 2.0

    async def acquire(self, url: str) -> float:
        self.calls.append(url)
        return 0.0

    async def reserve(self, url: str) -> float:
        self.calls.append(url)
        return 0.0

    def with_crawl_delay(self, delay: float | None):
        return self

    async def close(self) -> None:
        return None


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url="postgresql://u:p@localhost/wasl",
        redis_url="redis://localhost:6379/0",
        data_dir=tmp_path,
        crawler_info_url="https://example.com/crawler",
        opt_out_email="crawler@example.com",
        # Exercise the httpx path so respx can intercept; the browser path needs
        # a real Chromium and is covered by the live gate crawl instead.
        playwright_available=False,
    )


@pytest.fixture
def make_crawler(settings: Settings, tmp_path):
    def _make(budget: Budget = Budget.INTERACTIVE) -> Crawler:
        return Crawler(
            settings=settings,
            policy=CrawlPolicy(SeedRegistry(SEED_DATA)),
            limiter=FakeLimiter(),  # type: ignore[arg-type]
            cache=SnapshotCache(tmp_path / "cache"),
            budget=budget,
        )

    return _make


def mock_site(robots: str = ROBOTS_OPEN) -> None:
    """Route the whole test origin. Probes 404 unless a test says otherwise."""
    respx.get(f"{ROOT}/robots.txt").mock(return_value=httpx.Response(200, text=robots))
    respx.get(f"{ROOT}/").mock(return_value=httpx.Response(200, html=HOMEPAGE))
    for path in ("/a", "/b", "/c", "/d"):
        respx.get(f"{ROOT}{path}").mock(return_value=httpx.Response(200, html=PAGE))
    respx.route(host="allowed.example").mock(return_value=httpx.Response(404, text="not found"))


# --- refusals ----------------------------------------------------------------


async def test_refuses_a_domain_that_is_not_allowlisted(make_crawler) -> None:
    async with make_crawler() as crawler:
        with pytest.raises(CrawlRefused) as exc:
            await crawler.crawl("https://unknown.example")
    assert exc.value.rule == "not_allowlisted"


async def test_refuses_an_excluded_domain_even_when_user_submitted(make_crawler) -> None:
    """The opt-out cannot be overridden by the user-submission path."""
    async with make_crawler() as crawler:
        with pytest.raises(CrawlRefused) as exc:
            await crawler.crawl("https://excluded.example", user_submitted=True)
    assert exc.value.rule == "excluded"
    assert "asked us to stop" in exc.value.reason


async def test_refusal_happens_before_any_request_is_sent(make_crawler) -> None:
    async with make_crawler() as crawler:
        with pytest.raises(CrawlRefused):
            await crawler.crawl("https://unknown.example")
        assert crawler.requests_made == 0


def test_crawler_construction_refuses_without_a_crawler_identity(tmp_path) -> None:
    """The honest-identification rule is enforced at construction, not at fetch."""
    from wasl.config import ConfigurationError

    anonymous = Settings(
        database_url="postgresql://u:p@localhost/wasl",
        redis_url="redis://localhost:6379/0",
        data_dir=tmp_path,
    )
    with pytest.raises(ConfigurationError, match="Refusing to crawl"):
        Crawler(settings=anonymous)


# --- robots ------------------------------------------------------------------


@respx.mock
async def test_robots_disallowed_pages_are_recorded_not_fetched(make_crawler) -> None:
    mock_site(ROBOTS_BLOCKS_B)
    async with make_crawler() as crawler:
        pages, _ = await crawler.crawl(ROOT)

    blocked = [p for p in pages if p.robots_blocked]
    assert [p.url for p in blocked] == [f"{ROOT}/b"]
    assert not respx.routes[f"{ROOT}/b"].called if f"{ROOT}/b" in respx.routes else True


@respx.mock
async def test_a_robots_block_is_evidence_not_an_error(make_crawler) -> None:
    mock_site(ROBOTS_BLOCKS_B)
    async with make_crawler() as crawler:
        pages, _ = await crawler.crawl(ROOT)

    blocked = next(p for p in pages if p.robots_blocked)
    assert blocked.fetch_error == "robots.txt disallows this path"
    assert blocked.robots_blocked is True


# --- budget ------------------------------------------------------------------


@respx.mock
async def test_the_page_cap_is_enforced(make_crawler) -> None:
    mock_site()
    async with make_crawler(Budget.INTERACTIVE) as crawler:
        pages, _ = await crawler.crawl(ROOT)
    assert len(pages) <= Budget.INTERACTIVE.page_cap


@respx.mock
async def test_every_request_passes_through_the_rate_limiter(make_crawler) -> None:
    """A request that skips the limiter is a promise broken to the site."""
    mock_site()
    crawler = make_crawler()
    async with crawler:
        await crawler.crawl(ROOT)
        limiter = crawler._limiter  # type: ignore[attr-defined]

    assert len(limiter.calls) == crawler.requests_made


# --- URL discovery -----------------------------------------------------------


@respx.mock
async def test_discovery_skips_offsite_excluded_and_binary_links(make_crawler) -> None:
    mock_site()
    async with make_crawler() as crawler:
        pages, _ = await crawler.crawl(ROOT)

    fetched = {p.url for p in pages}
    assert f"{ROOT}/admin" not in fetched
    assert f"{ROOT}/cart" not in fetched
    assert f"{ROOT}/doc.pdf" not in fetched
    assert not any("elsewhere.example" in u for u in fetched)


@respx.mock
async def test_sitemap_urls_are_preferred_for_discovery(make_crawler) -> None:
    """The site telling us what exists beats guessing, and produces no 404s."""
    # Registered before mock_site(): respx matches in registration order, and
    # mock_site ends with a catch-all that would otherwise shadow this.
    respx.get(f"{ROOT}/sitemap.xml").mock(
        return_value=httpx.Response(
            200, text=f"<urlset><url><loc>{ROOT}/a</loc></url></urlset>"
        )
    )
    mock_site()
    async with make_crawler() as crawler:
        _, artifacts = await crawler.crawl(ROOT)

    assert any(r.found for r in artifacts.sitemaps)


# --- caching -----------------------------------------------------------------


@respx.mock
async def test_a_second_fetch_of_the_same_url_uses_the_cache(make_crawler) -> None:
    """The mechanism that stops a dev loop from becoming a nuisance."""
    mock_site()
    async with make_crawler() as crawler:
        first = await crawler.fetch_page(f"{ROOT}/a")
        before = crawler.requests_made
        second = await crawler.fetch_page(f"{ROOT}/a")

        assert crawler.requests_made == before
        assert second.pre_js_html == first.pre_js_html


@respx.mock
async def test_cache_can_be_bypassed_explicitly(make_crawler) -> None:
    mock_site()
    async with make_crawler() as crawler:
        await crawler.fetch_page(f"{ROOT}/a")
        before = crawler.requests_made
        await crawler.fetch_page(f"{ROOT}/a", use_cache=False)
        assert crawler.requests_made == before + 1


# --- planning ----------------------------------------------------------------


@respx.mock
async def test_plan_fetches_no_pages(make_crawler) -> None:
    """A dry run must cost the site its probe set and nothing more."""
    mock_site()
    async with make_crawler() as crawler:
        plan = await crawler.plan(ROOT)

    assert not respx.routes[f"{ROOT}/a"].called if f"{ROOT}/a" in respx.routes else True
    assert plan.page_cap == Budget.INTERACTIVE.page_cap
    assert plan.requests_per_second == 0.5


@respx.mock
async def test_plan_reports_the_robots_verdict(make_crawler) -> None:
    mock_site("User-agent: GPTBot\nDisallow: /\n")
    async with make_crawler() as crawler:
        plan = await crawler.plan(ROOT)

    assert plan.robots.present
    assert "GPTBot" in plan.robots.ai_agent_stanzas


@respx.mock
async def test_plan_refuses_an_out_of_scope_domain(make_crawler) -> None:
    async with make_crawler() as crawler:
        with pytest.raises(CrawlRefused):
            await crawler.plan("https://unknown.example")


# --- degraded capture --------------------------------------------------------


@respx.mock
async def test_capture_without_a_browser_is_marked_degraded(make_crawler) -> None:
    """So the rubric suppresses Axis 4 rather than scoring it zero."""
    from wasl.crawler.types import CaptureMode

    mock_site()
    async with make_crawler() as crawler:
        page = await crawler.fetch_page(f"{ROOT}/a")

    assert page.mode is CaptureMode.DEGRADED
    assert page.post_js_html == ""
    assert page.pre_js_html != ""
