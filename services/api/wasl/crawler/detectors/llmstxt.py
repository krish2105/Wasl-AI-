"""llms.txt evidence (Axis 1, 4 points — the single heaviest check on that axis).

`llms.txt` is a community convention, not a standard: a root-level markdown file
giving an agent a curated summary and links to the parts of the site worth
reading. Finding one is the clearest possible signal that a site has thought
about machine readers, which is why it carries more weight than robots.txt or a
sitemap.

We check that it is markdown-shaped rather than just present. A site serving its
SPA shell at every unmatched path — which is common — returns HTTP 200 for
/llms.txt with a mouthful of HTML, and scoring that as a real llms.txt would be a
false positive worth avoiding.
"""

from __future__ import annotations

import re

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import FetchedResource, SiteArtifacts

LLMS_TXT_PATH = "/llms.txt"

_H1 = re.compile(r"^\s{0,3}#\s+\S", re.MULTILINE)
_LINK = re.compile(r"\[[^\]]+\]\([^)]+\)")
_HTML_SHELL = re.compile(r"<\s*(html|!doctype|head|body|script)\b", re.IGNORECASE)


def looks_like_markdown(text: str) -> bool:
    """True when the body is plausibly a real llms.txt rather than an SPA shell."""
    if _HTML_SHELL.search(text[:2000]):
        return False
    return bool(_H1.search(text)) or len(_LINK.findall(text)) >= 2


def _summarise(resource: FetchedResource) -> str:
    lines = [ln for ln in resource.text.splitlines() if ln.strip()][:25]
    return "\n".join(lines)


def detect(artifacts: SiteArtifacts) -> list[Evidence]:
    resource = artifacts.llms_txt
    root = artifacts.root_url.rstrip("/") + LLMS_TXT_PATH

    if resource is None or not resource.found:
        status = f"HTTP {resource.status_code}" if resource else "not fetched"
        return [
            Evidence(
                source_url=root,
                kind="llmstxt",
                selector="llms.txt#absent",
                raw=f"No llms.txt at the site root ({status}).",
                phase="pre_js",
            )
        ]

    if not looks_like_markdown(resource.text):
        return [
            Evidence(
                source_url=resource.url,
                kind="llmstxt",
                selector="llms.txt#not-markdown",
                raw=(
                    "A response was returned for /llms.txt but it is not markdown — "
                    "most likely the site's catch-all HTML shell, not a real llms.txt.\n"
                    + resource.text[:400]
                ),
                phase="pre_js",
            )
        ]

    headings = _H1.findall(resource.text)
    links = _LINK.findall(resource.text)

    return [
        Evidence(
            source_url=resource.url,
            kind="llmstxt",
            selector="llms.txt#present",
            raw=(
                f"llms.txt present: {len(headings)} H1, {len(links)} links, "
                f"{len(resource.text)} chars.\n\n" + _summarise(resource)
            ),
            phase="pre_js",
        )
    ]
