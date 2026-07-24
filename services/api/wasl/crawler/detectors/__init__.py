"""Detectors: evidence extraction, with no model anywhere near it.

Every detector is a pure function. No network calls, no database, no globals, no
LLM. Given the same captured page it returns the same evidence, which is what
makes the score reproducible and the whole system testable against fixtures
instead of against the live web.

Two signatures, split by scope:

    PageDetector  (CapturedPage)  -> list[Evidence]
    SiteDetector  (SiteArtifacts) -> list[Evidence]

Site detectors exist because robots.txt, llms.txt, sitemaps and `.well-known`
describe an origin rather than a page. They are still pure — the fetching happens
in `crawler.fetch`, and they receive the already-fetched text.

Adding a detector means adding it to the tuples at the bottom of this module.
Nothing else discovers them, deliberately: implicit registration by import side
effect makes test isolation miserable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.crawler.types import CapturedPage, SiteArtifacts

PageDetector = Callable[[CapturedPage], list[Evidence]]
SiteDetector = Callable[[SiteArtifacts], list[Evidence]]

from wasl.crawler.detectors import (  # noqa: E402  (registry needs the symbols)
    forms,
    headers,
    identifiers,
    injection,
    jsonld,
    llmstxt,
    media,
    openapi,
    pagination,
    rendering,
    robots_txt,
    semantics,
    sitemap,
    wellknown,
)

PAGE_DETECTORS: tuple[tuple[str, PageDetector], ...] = (
    ("jsonld", jsonld.detect),
    ("forms", forms.detect),
    ("semantics", semantics.detect),
    ("identifiers", identifiers.detect),
    ("rendering", rendering.detect),
    ("headers", headers.detect),
    ("pagination", pagination.detect),
    ("media", media.detect),
    ("openapi_links", openapi.detect_page_links),
    ("injection", injection.detect),
)

SITE_DETECTORS: tuple[tuple[str, SiteDetector], ...] = (
    ("robots_txt", robots_txt.detect),
    ("sitemap", sitemap.detect),
    ("llmstxt", llmstxt.detect),
    ("wellknown", wellknown.detect),
    ("openapi_specs", openapi.detect_specs),
)


def run_page_detectors(page: CapturedPage) -> list[Evidence]:
    """Run every page detector. One failing detector must not lose the others."""
    collected: list[Evidence] = []
    for name, detector in PAGE_DETECTORS:
        try:
            collected.extend(detector(page))
        except Exception as exc:  # pragma: no cover - defensive
            import logging

            logging.getLogger(__name__).warning(
                "Detector %s failed on %s: %s: %s", name, page.url, type(exc).__name__, exc
            )
    return collected


def run_site_detectors(artifacts: SiteArtifacts) -> list[Evidence]:
    collected: list[Evidence] = []
    for name, detector in SITE_DETECTORS:
        try:
            collected.extend(detector(artifacts))
        except Exception as exc:  # pragma: no cover - defensive
            import logging

            logging.getLogger(__name__).warning(
                "Site detector %s failed on %s: %s: %s",
                name,
                artifacts.domain,
                type(exc).__name__,
                exc,
            )
    return collected


def extract_all(pages: Iterable[CapturedPage], artifacts: SiteArtifacts) -> EvidenceStore:
    """Full extraction pass over a crawl. Deduplication is free — IDs are content-addressed."""
    store = EvidenceStore()
    store.extend(run_site_detectors(artifacts))
    for page in pages:
        if page.ok:
            store.extend(run_page_detectors(page))
    return store


__all__ = [
    "PAGE_DETECTORS",
    "SITE_DETECTORS",
    "PageDetector",
    "SiteDetector",
    "extract_all",
    "run_page_detectors",
    "run_site_detectors",
]
