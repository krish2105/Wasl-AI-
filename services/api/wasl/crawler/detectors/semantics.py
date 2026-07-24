"""Semantic HTML evidence (Axis 4, 4 points).

Landmarks and a sane heading hierarchy are the cheapest proxy for extractability
there is. An agent that can find `<main>` can skip the nav, the cookie banner and
the footer without heuristics; one that cannot has to guess which `<div>` holds
the content.

Measured on the post-JS DOM when available, because frameworks routinely render
landmarks client-side and judging the raw body would understate most modern
sites.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage, Phase

LANDMARKS = ("main", "article", "nav", "header", "footer", "aside", "section")


def _analyse(html: str, url: str, phase: Phase) -> list[Evidence]:
    soup = BeautifulSoup(html, "lxml")
    evidence: list[Evidence] = []

    present = {name: len(soup.find_all(name)) for name in LANDMARKS}
    # ARIA landmarks are equivalent for an agent's purposes.
    aria_main = len(soup.find_all(attrs={"role": "main"}))
    aria_nav = len(soup.find_all(attrs={"role": "navigation"}))

    evidence.append(
        Evidence(
            source_url=url,
            kind="dom",
            selector="semantics#landmarks",
            raw=(
                "Landmark elements: "
                + ", ".join(f"<{name}>={count}" for name, count in present.items())
                + f", role=main:{aria_main}, role=navigation:{aria_nav}"
            ),
            phase=phase,
        )
    )

    headings = [(int(tag.name[1]), tag.get_text(" ", strip=True)[:80]) for tag in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6"]
    )]
    h1s = [text for level, text in headings if level == 1]

    skips: list[str] = []
    previous = 0
    for level, text in headings:
        if previous and level > previous + 1:
            skips.append(f"h{previous} -> h{level} at {text!r}")
        previous = level

    evidence.append(
        Evidence(
            source_url=url,
            kind="dom",
            selector="semantics#headings",
            raw=(
                f"{len(headings)} headings, {len(h1s)} <h1>.\n"
                f"h1 text: {h1s[:3]}\n"
                f"hierarchy skips: {skips[:5] if skips else 'none'}\n"
                + "\n".join(f"  {'  ' * (level - 1)}h{level}: {text}" for level, text in headings[:25])
            ),
            phase=phase,
        )
    )

    lang = soup.html.get("lang") if soup.html else None
    title = soup.title.get_text(strip=True) if soup.title else None
    description = soup.find("meta", attrs={"name": "description"})

    evidence.append(
        Evidence(
            source_url=url,
            kind="meta",
            selector="semantics#document",
            raw=(
                f"lang={lang!r}\n"
                f"title={title!r}\n"
                f"meta description={(description.get('content') if description else None)!r}"
            ),
            phase=phase,
        )
    )

    return evidence


def detect(page: CapturedPage) -> list[Evidence]:
    phases = page.available_phases
    phase: Phase = "post_js" if "post_js" in phases else "pre_js"
    html = page.html_for(phase)
    if not html.strip():
        return []
    return _analyse(html, page.final_url, phase)
