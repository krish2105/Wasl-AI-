"""Structured-data evidence: JSON-LD, microdata, RDFa (Axis 2, 20 points).

Uses `extruct`, which handles all three syntaxes and their many malformed
variants far better than anything hand-rolled.

One decision worth spelling out, because it shapes Axis 2's ceiling: this
detector records **what was found and whether it parses**, not whether it is
*valid* against the schema.org vocabulary. Validity is a Phase 3 scoring concern,
checked against a versioned required-property table, because "required property"
is not a concept schema.org actually defines — it is an operational definition we
have to write down and defend rather than pretend to inherit.

Extraction runs on the post-JS DOM when available. Plenty of sites inject their
JSON-LD via a tag manager, and judging them on the raw response body alone would
report a false negative.
"""

from __future__ import annotations

import json
from typing import Any

import extruct

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage, Phase

# The entity types Axis 2 scores for coverage, plus Organization/LocalBusiness
# which have their own check.
TRACKED_TYPES: frozenset[str] = frozenset(
    {
        "Organization",
        "LocalBusiness",
        "Product",
        "Service",
        "Offer",
        "Event",
        "FAQPage",
        "OpeningHoursSpecification",
    }
)

_SYNTAXES = ("json-ld", "microdata", "rdfa")
_KIND_FOR = {"json-ld": "jsonld", "microdata": "microdata", "rdfa": "rdfa"}


def _type_names(node: Any) -> list[str]:
    """Every @type on a node, normalised to a bare name."""
    if not isinstance(node, dict):
        return []
    raw = node.get("@type") or node.get("type")
    values = raw if isinstance(raw, list) else [raw]
    names: list[str] = []
    for value in values:
        if isinstance(value, str) and value:
            names.append(value.rsplit("/", 1)[-1].rsplit("#", 1)[-1])
    return names


def walk_entities(node: Any, depth: int = 0) -> list[dict]:
    """Flatten a structured-data tree into the typed nodes it contains.

    Nested entities count: a Product carrying an Offer is two pieces of coverage,
    and a crawler that only looked at top level would miss most real markup.
    Depth-capped because @graph structures can be deep and occasionally cyclic.
    """
    if depth > 6:
        return []

    found: list[dict] = []
    if isinstance(node, dict):
        if _type_names(node):
            found.append(node)
        for key, value in node.items():
            if key in {"@context"}:
                continue
            found.extend(walk_entities(value, depth + 1))
    elif isinstance(node, list):
        for item in node:
            found.extend(walk_entities(item, depth + 1))
    return found


def _serialise(node: dict, limit: int = 1500) -> str:
    try:
        return json.dumps(node, indent=2, ensure_ascii=False)[:limit]
    except (TypeError, ValueError):
        return str(node)[:limit]


def _extract(html: str, base_url: str) -> dict[str, list]:
    try:
        return extruct.extract(html, base_url=base_url, syntaxes=list(_SYNTAXES), uniform=True)
    except Exception:
        return {syntax: [] for syntax in _SYNTAXES}


def _detect_phase(page: CapturedPage, phase: Phase) -> list[Evidence]:
    html = page.html_for(phase)
    if not html.strip():
        return []

    data = _extract(html, page.final_url)
    evidence: list[Evidence] = []

    for syntax in _SYNTAXES:
        nodes = data.get(syntax) or []
        if not nodes:
            continue

        kind = _KIND_FOR[syntax]
        entities = walk_entities(nodes)

        if not entities:
            evidence.append(
                Evidence(
                    source_url=page.final_url,
                    kind=kind,
                    selector=f"{syntax}#untyped",
                    raw=f"{syntax} present but no node carries an @type.\n{_serialise(nodes[0])}",
                    phase=phase,
                )
            )
            continue

        emitted: set[str] = set()
        for entity in entities:
            for type_name in _type_names(entity):
                if type_name in emitted:
                    continue
                emitted.add(type_name)
                evidence.append(
                    Evidence(
                        source_url=page.final_url,
                        kind=kind,
                        selector=f"{syntax}#{type_name}",
                        raw=_serialise(entity),
                        phase=phase,
                    )
                )

    return evidence


def detect(page: CapturedPage) -> list[Evidence]:
    """Prefer the hydrated DOM; fall back to the raw body on a degraded capture."""
    phases = page.available_phases
    if "post_js" in phases:
        found = _detect_phase(page, "post_js")
        if found:
            return found
    if "pre_js" in phases:
        return _detect_phase(page, "pre_js")
    return []
