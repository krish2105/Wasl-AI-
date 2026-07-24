"""Pagination evidence (Axis 4, 3 points).

Infinite scroll is invisible to an agent. If page two only exists after a scroll
event fires an XHR, there is no URL to fetch and no way to enumerate a catalogue
without driving a browser. Crawlable pagination — `rel="next"`, `?page=2`,
numbered links — is what makes a listing exhaustible.

The detector reports both signals rather than one verdict, because the two
coexist constantly: plenty of sites ship numbered links for crawlers *and*
infinite scroll for humans, and that is a genuinely good outcome that a single
boolean would misreport.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage

PAGE_QUERY_KEYS = ("page", "p", "pg", "offset", "start", "from", "skip", "cursor")

_PAGE_PATH = re.compile(r"/(page|p)[/-]?(\d+)/?$", re.IGNORECASE)

_INFINITE_SCROLL_MARKERS = re.compile(
    r"(infinite[-_\s]?scroll|data-infinite|IntersectionObserver|"
    r"load[-_\s]?more|loadMore|showMore|data-load-more|"
    r"react-infinite|vue-infinite-loading|scroll-?trigger-?load)",
    re.IGNORECASE,
)

_NUMBERED_LINK_TEXT = re.compile(r"^\s*(\d{1,3}|next|prev|previous|»|«|›|‹)\s*$", re.IGNORECASE)


def detect(page: CapturedPage) -> list[Evidence]:
    phases = page.available_phases
    phase = "post_js" if "post_js" in phases else "pre_js"
    html = page.html_for(phase)
    if not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")
    evidence: list[Evidence] = []

    # rel="next" / rel="prev" — the explicit, standardised signal.
    rel_links: list[str] = []
    for rel in ("next", "prev", "previous"):
        for tag in soup.find_all(["link", "a"], rel=lambda v, r=rel: bool(v) and r in str(v).lower()):
            href = tag.get("href")
            if href:
                rel_links.append(f'<{tag.name} rel="{rel}" href="{href}">')

    if rel_links:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="pagination",
                selector="pagination#rel",
                raw="Explicit rel next/prev links:\n" + "\n".join(dict.fromkeys(rel_links))[:1500],
                phase=phase,
            )
        )

    # Numbered / parameterised page URLs.
    page_urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(("#", "javascript:")):
            continue
        absolute = urljoin(page.final_url, href)
        parsed = urlparse(absolute)

        query = parse_qs(parsed.query)
        has_page_param = any(k.lower() in PAGE_QUERY_KEYS for k in query)
        has_page_path = bool(_PAGE_PATH.search(parsed.path))
        label = anchor.get_text(" ", strip=True)

        if has_page_param or has_page_path or _NUMBERED_LINK_TEXT.match(label):
            if (has_page_param or has_page_path) and absolute not in page_urls:
                page_urls.append(absolute)

    if page_urls:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="pagination",
                selector="pagination#crawlable-urls",
                raw=(
                    f"{len(page_urls)} crawlable pagination URL(s) — an agent can enumerate "
                    f"this listing without executing JavaScript.\n" + "\n".join(page_urls[:12])
                ),
                phase=phase,
            )
        )

    # Infinite scroll — recorded whether or not crawlable URLs also exist.
    scroll_hit = _INFINITE_SCROLL_MARKERS.search(html[:400_000])
    if scroll_hit:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="pagination",
                selector="pagination#infinite-scroll",
                raw=(
                    f"Infinite-scroll or load-more marker found: {scroll_hit.group(0)!r}. "
                    + (
                        "Crawlable pagination URLs also exist, so content remains enumerable."
                        if page_urls or rel_links
                        else "No crawlable pagination URLs were found alongside it — later "
                        "results may be unreachable without a browser."
                    )
                ),
                phase=phase,
            )
        )

    if not evidence:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="pagination",
                selector="pagination#none",
                raw="No pagination controls detected on this page.",
                phase=phase,
            )
        )

    return evidence
