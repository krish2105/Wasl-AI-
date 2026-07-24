"""Sitemap evidence (Axis 1).

A sitemap is the cheapest possible answer to "what is on this site", which makes
it both a scoring signal and — during the crawl itself — the politest way to plan
which pages to fetch. Guessing URLs generates 404s on someone else's server; a
sitemap does not.
"""

from __future__ import annotations

import re

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import SiteArtifacts

_LOC = re.compile(r"<loc>\s*(?P<url>[^<\s]+)\s*</loc>", re.IGNORECASE)
_IS_INDEX = re.compile(r"<sitemapindex", re.IGNORECASE)
_LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.IGNORECASE)


def parse_urls(xml: str) -> list[str]:
    """URLs listed in a sitemap or sitemap index. Regex, not a parser.

    Deliberate: sitemaps in the wild are frequently malformed, oversized, or
    served with a wrong content type, and a strict XML parse fails on all three.
    We only need the `<loc>` values, and a regex gets them from documents lxml
    rejects outright.
    """
    return [m.group("url").strip() for m in _LOC.finditer(xml)]


def is_index(xml: str) -> bool:
    return bool(_IS_INDEX.search(xml))


def detect(artifacts: SiteArtifacts) -> list[Evidence]:
    evidence: list[Evidence] = []

    if not artifacts.sitemaps:
        return [
            Evidence(
                source_url=artifacts.root_url,
                kind="sitemap",
                selector="sitemap#absent",
                raw="No sitemap was reachable at /sitemap.xml or declared in robots.txt.",
                phase="pre_js",
            )
        ]

    for resource in artifacts.sitemaps:
        if not resource.found:
            evidence.append(
                Evidence(
                    source_url=resource.url,
                    kind="sitemap",
                    selector="sitemap#unreachable",
                    raw=(
                        f"Sitemap not retrievable: HTTP {resource.status_code}"
                        f"{f' ({resource.fetch_error})' if resource.fetch_error else ''}"
                    ),
                    phase="pre_js",
                )
            )
            continue

        urls = parse_urls(resource.text)
        kind_label = "sitemap index" if is_index(resource.text) else "sitemap"
        lastmods = _LASTMOD.findall(resource.text)

        evidence.append(
            Evidence(
                source_url=resource.url,
                kind="sitemap",
                selector="sitemap#present",
                raw=(
                    f"{kind_label} reachable with {len(urls)} <loc> entries"
                    f"{f', {len(lastmods)} with <lastmod>' if lastmods else ''}.\n"
                    + "\n".join(urls[:20])
                ),
                phase="pre_js",
            )
        )

    return evidence
