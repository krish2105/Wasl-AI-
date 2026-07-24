"""Snapshot cache.

The cache is a politeness mechanism as much as a performance one: it is what
stops a debugging session from quietly sending a site fifty requests. So the test
that matters is the round trip — if a snapshot does not reload faithfully,
someone re-crawls, and the site pays for it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from wasl.crawler.cache import SnapshotCache
from wasl.crawler.types import CaptureMode, CapturedPage

URL = "https://example.com/catalogue"


@pytest.fixture
def cache(tmp_path: Path) -> SnapshotCache:
    return SnapshotCache(tmp_path / "cache")


def make_page(**overrides) -> CapturedPage:
    payload = {
        "url": URL,
        "final_url": URL,
        "status_code": 200,
        "headers": {"content-type": "text/html", "x-ratelimit-limit": "100"},
        "pre_js_html": "<html><body><p>raw response</p></body></html>",
        "post_js_html": "<html><body><p>raw response</p><p>hydrated</p></body></html>",
        "mode": CaptureMode.FULL,
        "response_time_ms": 342,
        "fetched_at": datetime.now(UTC),
    }
    payload.update(overrides)
    return CapturedPage(**payload)  # type: ignore[arg-type]


def test_a_missing_snapshot_returns_none(cache: SnapshotCache) -> None:
    assert cache.get(URL) is None
    assert cache.has(URL) is False


def test_snapshot_round_trips_faithfully(cache: SnapshotCache) -> None:
    original = make_page()
    cache.put(original)

    restored = cache.get(URL)

    assert restored is not None
    assert restored.url == original.url
    assert restored.final_url == original.final_url
    assert restored.status_code == original.status_code
    assert restored.headers == original.headers
    assert restored.pre_js_html == original.pre_js_html
    assert restored.post_js_html == original.post_js_html
    assert restored.mode is CaptureMode.FULL
    assert restored.response_time_ms == original.response_time_ms


def test_degraded_captures_round_trip_as_degraded(cache: SnapshotCache) -> None:
    """The mode must survive: it decides whether Axis 4 is scored or suppressed."""
    cache.put(make_page(post_js_html="", mode=CaptureMode.DEGRADED))
    restored = cache.get(URL)
    assert restored is not None
    assert restored.mode is CaptureMode.DEGRADED
    assert restored.post_js_html == ""


def test_robots_blocked_pages_are_cached_too(cache: SnapshotCache) -> None:
    """A refusal we honoured is evidence, and re-fetching to rediscover it is rude."""
    cache.put(
        make_page(
            pre_js_html="",
            post_js_html="",
            status_code=0,
            robots_blocked=True,
            fetch_error="robots.txt disallows this path",
            mode=CaptureMode.DEGRADED,
        )
    )
    restored = cache.get(URL)
    assert restored is not None
    assert restored.robots_blocked is True
    assert restored.fetch_error == "robots.txt disallows this path"


def test_snapshots_are_keyed_by_date(cache: SnapshotCache) -> None:
    """A snapshot is a point-in-time record, not a permanent answer."""
    yesterday = datetime.now(UTC) - timedelta(days=1)
    cache.put(make_page(pre_js_html="<p>old</p>", fetched_at=yesterday))

    assert cache.get(URL) is None
    assert cache.get(URL, on=yesterday.date()) is not None


def test_latest_searches_backwards_for_the_newest_snapshot(cache: SnapshotCache) -> None:
    """Generated MCP servers read from cache so running one sends no traffic."""
    three_days_ago = datetime.now(UTC) - timedelta(days=3)
    cache.put(make_page(pre_js_html="<p>older</p>", fetched_at=three_days_ago))

    found = cache.latest(URL)

    assert found is not None
    assert "older" in found.pre_js_html


def test_latest_respects_its_horizon(cache: SnapshotCache) -> None:
    old = datetime.now(UTC) - timedelta(days=40)
    cache.put(make_page(fetched_at=old))
    assert cache.latest(URL, within_days=30) is None


def test_different_urls_do_not_collide(cache: SnapshotCache) -> None:
    cache.put(make_page(url="https://example.com/a", pre_js_html="<p>A</p>"))
    cache.put(make_page(url="https://example.com/b", pre_js_html="<p>B</p>"))

    a = cache.get("https://example.com/a")
    b = cache.get("https://example.com/b")

    assert a is not None and "A" in a.pre_js_html
    assert b is not None and "B" in b.pre_js_html


def test_corrupt_metadata_is_ignored_rather_than_raised(cache: SnapshotCache) -> None:
    """A damaged cache entry should cost a re-fetch, not crash the crawl."""
    cache.put(make_page())
    meta = next(cache.root.rglob("*.meta.json"))
    meta.write_text("{ this is not json")

    assert cache.get(URL) is None


def test_bodies_live_on_disk_not_in_the_metadata(cache: SnapshotCache) -> None:
    """Third-party page content stays out of the database by construction."""
    cache.put(make_page())
    meta = next(cache.root.rglob("*.meta.json"))
    assert "raw response" not in meta.read_text()
    assert len(list(cache.root.rglob("*.pre.html"))) == 1
    assert len(list(cache.root.rglob("*.post.html"))) == 1
