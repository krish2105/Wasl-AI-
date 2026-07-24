"""Stable machine identifier evidence (Axis 5, 5 points).

Stable IDs are what make a site *transactable* rather than merely readable. An
agent that can say "product 4471-B" and get the same thing tomorrow can build a
workflow. One that can only say "the third card on the page" cannot.

Two sources, and they are not equally good:

- **Structured markup** — `sku`, `productID`, `gtin`, `identifier` in JSON-LD.
  Unambiguous, and the strongest form of this signal.
- **URL structure** — `/product/12345`, `?id=6789`, `/listing/ab12cd`. Inferred,
  so it needs corroboration: a pattern seen once could be anything. This detector
  reports the pattern and how many distinct URLs share it, and leaves the
  threshold decision to Phase 3.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage

# JSON-LD keys that carry a durable identifier.
ID_PROPERTIES = (
    "sku", "productID", "productId", "gtin", "gtin8", "gtin12", "gtin13", "gtin14",
    "mpn", "isbn", "identifier", "serialNumber", "orderNumber",
)

# Query parameters conventionally holding a record ID.
ID_QUERY_KEYS = ("id", "pid", "sku", "product_id", "productid", "listing_id", "item", "itemid", "ref")

# A path segment that looks like a record ID: numeric, or a slug ending in one.
_NUMERIC_SEGMENT = re.compile(r"^\d{3,}$")
_SLUG_WITH_ID = re.compile(r"^(?P<slug>[a-z0-9-]*?)-?(?P<id>\d{4,}|[a-f0-9]{8,})$", re.IGNORECASE)

_ID_CONTAINER_SEGMENTS = (
    "product", "products", "p", "item", "items", "listing", "listings",
    "property", "properties", "car", "cars", "vehicle", "hotel", "hotels",
    "room", "sku", "detail", "details", "dp", "offer", "offers",
)


def _walk(node: object, depth: int = 0) -> list[dict]:
    if depth > 6:
        return []
    out: list[dict] = []
    if isinstance(node, dict):
        out.append(node)
        for value in node.values():
            out.extend(_walk(value, depth + 1))
    elif isinstance(node, list):
        for item in node:
            out.extend(_walk(item, depth + 1))
    return out


def _structured_ids(html: str, url: str) -> list[Evidence]:
    soup = BeautifulSoup(html, "lxml")
    evidence: list[Evidence] = []
    seen: set[tuple[str, str]] = set()

    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            payload = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        for node in _walk(payload):
            for prop in ID_PROPERTIES:
                if prop not in node:
                    continue
                value = node[prop]
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)[:200]
                value = str(value).strip()
                if not value or (prop, value) in seen:
                    continue
                seen.add((prop, value))
                type_name = node.get("@type", "?")
                evidence.append(
                    Evidence(
                        source_url=url,
                        kind="identifier",
                        selector=f"jsonld#{type_name}.{prop}",
                        raw=f"{type_name}.{prop} = {value}",
                        phase="post_js",
                    )
                )

    return evidence[:25]


def _url_pattern(path: str) -> tuple[str, str] | None:
    """Return (generalised pattern, the id found), or None."""
    segments = [s for s in path.split("/") if s]
    for index, segment in enumerate(segments):
        previous = segments[index - 1].lower() if index else ""
        is_container = previous in _ID_CONTAINER_SEGMENTS

        if _NUMERIC_SEGMENT.match(segment) and (is_container or index > 0):
            generalised = "/".join(
                ["{id}" if i == index else s for i, s in enumerate(segments)]
            )
            return f"/{generalised}", segment

        match = _SLUG_WITH_ID.match(segment)
        if match and is_container:
            generalised = "/".join(
                ["{slug}-{id}" if i == index else s for i, s in enumerate(segments)]
            )
            return f"/{generalised}", match.group("id")

    return None


def _url_ids(html: str, page_url: str) -> list[Evidence]:
    soup = BeautifulSoup(html, "lxml")
    patterns: dict[str, list[str]] = defaultdict(list)
    query_hits: dict[str, list[str]] = defaultdict(list)

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc != urlparse(page_url).netloc:
            continue

        found = _url_pattern(parsed.path)
        if found:
            pattern, identifier = found
            if absolute not in patterns[pattern]:
                patterns[pattern].append(absolute)

        for key, values in parse_qs(parsed.query).items():
            if key.lower() in ID_QUERY_KEYS and values and values[0]:
                marker = f"{parsed.path}?{key}="
                if absolute not in query_hits[marker]:
                    query_hits[marker].append(absolute)

    evidence: list[Evidence] = []

    for pattern, urls in sorted(patterns.items(), key=lambda kv: -len(kv[1]))[:10]:
        evidence.append(
            Evidence(
                source_url=page_url,
                kind="identifier",
                selector=f"url-pattern#{pattern}",
                raw=(
                    f"Stable URL pattern {pattern} seen on {len(urls)} distinct link(s).\n"
                    + "\n".join(urls[:8])
                ),
                phase="post_js",
            )
        )

    for marker, urls in sorted(query_hits.items(), key=lambda kv: -len(kv[1]))[:8]:
        evidence.append(
            Evidence(
                source_url=page_url,
                kind="identifier",
                selector=f"url-query#{marker}",
                raw=(
                    f"Identifier query parameter at {marker} on {len(urls)} distinct link(s).\n"
                    + "\n".join(urls[:8])
                ),
                phase="post_js",
            )
        )

    return evidence


def detect(page: CapturedPage) -> list[Evidence]:
    phases = page.available_phases
    html = page.html_for("post_js" if "post_js" in phases else "pre_js")
    if not html.strip():
        return []
    return _structured_ids(html, page.final_url) + _url_ids(html, page.final_url)
