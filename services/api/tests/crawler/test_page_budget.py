"""Guards against the two ways a crawl can waste its budget on non-content.

Both were found by running the golden scan rather than by reading the code, and
both had the same symptom: a scan that appeared hung while a Python process sat
at 99% CPU.

The cause was a 50 MB products sitemap from Ounass being crawled as if it were a
page, then parsed by all fifteen detectors. The injection scanner alone takes
~13 seconds on a document that size.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wasl.crawler.detectors import run_page_detectors
from wasl.crawler.fetch import _looks_like_sitemap
from wasl.crawler.policy import MAX_PARSEABLE_BYTES
from wasl.crawler.types import CaptureMode, CapturedPage


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/sitemap.xml",
        "https://example.com/sitemap/partition-0.xml",
        "https://www.ounass.ae/sitemaps/products_2.xml",
        "https://example.com/sitemap_index.xml.gz",
        "https://example.com/sitemaps/",
    ],
)
def test_sitemaps_are_recognised(url: str) -> None:
    assert _looks_like_sitemap(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/products",
        "https://example.com/product/12345",
        "https://example.com/about",
    ],
)
def test_content_urls_are_not_mistaken_for_sitemaps(url: str) -> None:
    assert not _looks_like_sitemap(url)


def _page(size: int) -> CapturedPage:
    html = "<html><body>" + ("<div>x</div>" * (size // 12)) + "</body></html>"
    return CapturedPage(
        url="https://example.com/feed",
        final_url="https://example.com/feed",
        status_code=200,
        headers={},
        pre_js_html=html,
        post_js_html="",
        mode=CaptureMode.DEGRADED,
        response_time_ms=100,
        fetched_at=datetime.now(UTC),
    )


def test_oversized_documents_are_not_parsed() -> None:
    """A 4 MB document must not reach the detectors, or one page costs minutes."""
    evidence = run_page_detectors(_page(MAX_PARSEABLE_BYTES + 1_000_000))

    assert len(evidence) == 1
    assert evidence[0].selector == "page#too-large"


def test_the_refusal_is_recorded_rather_than_silent() -> None:
    """'We declined to parse this' is a fact about the crawl and belongs in evidence."""
    evidence = run_page_detectors(_page(MAX_PARSEABLE_BYTES + 1_000_000))
    assert "MB parse limit" in evidence[0].raw


def test_normal_pages_are_still_parsed() -> None:
    evidence = run_page_detectors(_page(50_000))
    assert len(evidence) > 1
    assert not any((e.selector or "") == "page#too-large" for e in evidence)
