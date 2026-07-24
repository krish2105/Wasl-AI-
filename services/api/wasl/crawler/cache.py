"""Snapshot cache for fetched pages.

The most common way to become a nuisance is not malice, it is a dev loop. Re-run
a detector twenty times while debugging and a site has quietly received twenty
requests it did not need to serve. Caching by URL and date removes that entirely:
the crawl happens once, and every subsequent run reads from disk.

It also makes the demo deterministic, which matters when the demo is being shown
live to someone.

Bodies live on disk, not in Postgres. Storing third-party page content is
justifiable as internal evidence; it is not something we republish, and keeping
it out of the database keeps that boundary visible rather than incidental.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

from wasl.config import get_settings
from wasl.crawler.types import CaptureMode, CapturedPage

logger = logging.getLogger(__name__)

_META_SUFFIX = ".meta.json"
_PRE_SUFFIX = ".pre.html"
_POST_SUFFIX = ".post.html"


def _key_for(url: str, on: date) -> str:
    """Cache key: URL hash plus the date, so a snapshot is a point-in-time record."""
    return f"{on.isoformat()}/{hashlib.sha256(url.encode()).hexdigest()[:24]}"


class SnapshotCache:
    """Disk-backed store of captured pages, keyed by URL and date."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or get_settings().cache_dir

    @property
    def root(self) -> Path:
        return self._root

    def _paths(self, url: str, on: date) -> tuple[Path, Path, Path]:
        base = self._root / _key_for(url, on)
        return (
            base.with_name(base.name + _META_SUFFIX),
            base.with_name(base.name + _PRE_SUFFIX),
            base.with_name(base.name + _POST_SUFFIX),
        )

    def has(self, url: str, *, on: date | None = None) -> bool:
        meta, _, _ = self._paths(url, on or datetime.now(UTC).date())
        return meta.exists()

    def get(self, url: str, *, on: date | None = None) -> CapturedPage | None:
        """Read a snapshot back, or None if it was never taken."""
        meta_path, pre_path, post_path = self._paths(url, on or datetime.now(UTC).date())
        if not meta_path.exists():
            return None

        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            logger.warning("Corrupt cache metadata at %s; ignoring", meta_path)
            return None

        return CapturedPage(
            url=meta["url"],
            final_url=meta["final_url"],
            status_code=meta["status_code"],
            headers=meta["headers"],
            pre_js_html=pre_path.read_text() if pre_path.exists() else "",
            post_js_html=post_path.read_text() if post_path.exists() else "",
            mode=CaptureMode(meta["mode"]),
            response_time_ms=meta["response_time_ms"],
            fetched_at=datetime.fromisoformat(meta["fetched_at"]),
            robots_blocked=meta.get("robots_blocked", False),
            fetch_error=meta.get("fetch_error"),
        )

    def put(self, page: CapturedPage, *, on: date | None = None) -> None:
        """Write a snapshot. Overwrites the same URL on the same date."""
        on = on or page.fetched_at.date()
        meta_path, pre_path, post_path = self._paths(page.url, on)
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        if page.pre_js_html:
            pre_path.write_text(page.pre_js_html)
        if page.post_js_html:
            post_path.write_text(page.post_js_html)

        meta_path.write_text(
            json.dumps(
                {
                    "url": page.url,
                    "final_url": page.final_url,
                    "status_code": page.status_code,
                    "headers": page.headers,
                    "mode": page.mode.value,
                    "response_time_ms": page.response_time_ms,
                    "fetched_at": page.fetched_at.isoformat(),
                    "robots_blocked": page.robots_blocked,
                    "fetch_error": page.fetch_error,
                },
                indent=2,
            )
        )

    def latest(self, url: str, *, within_days: int = 30) -> CapturedPage | None:
        """Most recent snapshot of a URL, searching backwards from today.

        Used by generated MCP servers, which read from cache by default so that
        running someone's generated server does not send traffic to the site it
        was generated from.
        """
        today = datetime.now(UTC).date()
        for offset in range(within_days + 1):
            day = date.fromordinal(today.toordinal() - offset)
            page = self.get(url, on=day)
            if page is not None:
                return page
        return None
