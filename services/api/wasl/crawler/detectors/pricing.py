"""Pricing and availability evidence (Axis 5, 4 points; Axis 3, 2 points).

Axis 5 asks whether prices and availability are expressed in *structured markup*
rather than only as rendered text. That comparison needs both halves measured, so
this detector reports them separately:

- **structured** — `Offer.price`, `priceCurrency`, `availability` in JSON-LD or
  microdata. A machine can read this without guessing.
- **rendered** — currency amounts and stock language in visible text. A human
  can read it; an agent has to parse prose and hope.

A site with both is doing well. A site with only rendered text is the common
case, and the gap between those two is precisely what the check scores.

Currency handling is UAE-first — AED and د.إ are recognised alongside the usual
international symbols, because a rubric that cannot see a dirham is not much use
for scoring Emirati retail.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage
from wasl.crawler.detectors.rendering import meaningful_text

_CURRENCY_SYMBOLS = r"(?:AED|د\.إ|SAR|QAR|KWD|BHD|OMR|USD|EUR|GBP|INR|\$|€|£|₹|¥)"

# A currency token adjacent to a number, in either order.
_RENDERED_PRICE = re.compile(
    rf"(?:{_CURRENCY_SYMBOLS}\s?\d[\d,]*(?:\.\d{{1,2}})?"
    rf"|\d[\d,]*(?:\.\d{{1,2}})?\s?{_CURRENCY_SYMBOLS})",
    re.IGNORECASE,
)

_RENDERED_AVAILABILITY = re.compile(
    r"\b(in stock|out of stock|sold out|available now|unavailable|back ?order|"
    r"pre-?order|limited availability|only \d+ left|ships? (?:in|within))\b",
    re.IGNORECASE,
)

_PRICE_KEYS = ("price", "lowPrice", "highPrice", "priceCurrency", "priceSpecification")
_AVAILABILITY_KEYS = ("availability", "availabilityStarts", "inventoryLevel", "itemCondition")


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


def _structured(html: str, url: str, phase: str) -> list[Evidence]:
    soup = BeautifulSoup(html, "lxml")
    evidence: list[Evidence] = []
    prices: list[str] = []
    availability: list[str] = []

    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        try:
            payload = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        for node in _walk(payload):
            for key in _PRICE_KEYS:
                if key in node:
                    prices.append(f"{node.get('@type', '?')}.{key} = {node[key]}")
            for key in _AVAILABILITY_KEYS:
                if key in node:
                    availability.append(f"{node.get('@type', '?')}.{key} = {node[key]}")

    # Microdata: itemprop is the other common way to express this.
    for element in soup.find_all(attrs={"itemprop": re.compile(r"^(price|availability)$", re.I)}):
        prop = str(element.get("itemprop")).lower()
        value = element.get("content") or element.get_text(" ", strip=True)
        if not value:
            continue
        (prices if prop == "price" else availability).append(f"microdata itemprop={prop} = {value}")

    if prices:
        evidence.append(
            Evidence(
                source_url=url,
                kind="text",
                selector="pricing#structured-price",
                raw="Price expressed in structured markup:\n" + "\n".join(dict.fromkeys(prices))[:1500],
                phase=phase,  # type: ignore[arg-type]
            )
        )
    if availability:
        evidence.append(
            Evidence(
                source_url=url,
                kind="text",
                selector="pricing#structured-availability",
                raw=(
                    "Availability expressed in structured markup:\n"
                    + "\n".join(dict.fromkeys(availability))[:1500]
                ),
                phase=phase,  # type: ignore[arg-type]
            )
        )

    return evidence


def detect(page: CapturedPage) -> list[Evidence]:
    phases = page.available_phases
    if not phases:
        return []
    phase = "post_js" if "post_js" in phases else "pre_js"
    html = page.html_for(phase)
    if not html.strip():
        return []

    evidence = _structured(html, page.final_url, phase)

    text = meaningful_text(html)
    rendered_prices = _RENDERED_PRICE.findall(text)
    rendered_availability = _RENDERED_AVAILABILITY.findall(text)

    if rendered_prices:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="text",
                selector="pricing#rendered-price",
                raw=(
                    f"{len(rendered_prices)} price-like string(s) in rendered text only: "
                    + ", ".join(dict.fromkeys(rendered_prices))[:600]
                ),
                phase=phase,  # type: ignore[arg-type]
            )
        )

    if rendered_availability:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="text",
                selector="pricing#rendered-availability",
                raw=(
                    "Availability stated in rendered text only: "
                    + ", ".join(dict.fromkeys(a.lower() for a in rendered_availability))[:400]
                ),
                phase=phase,  # type: ignore[arg-type]
            )
        )

    return evidence
