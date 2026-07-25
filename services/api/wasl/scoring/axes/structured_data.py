"""Axis 2 — Structured Data Coverage (20 points, 4 checks).

Does the site describe itself in a vocabulary machines already understand?

The fourth check — "validates with zero required-property violations" — rests on
`schema_required.yaml`, which is Wasl's own operational definition rather than an
inherited standard. schema.org has no required properties; every term is
optional by design. That file explains the reasoning and the README says plainly
that the definition is ours. Scoring against an invented standard is defensible;
pretending it came from schema.org would not be.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import yaml

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.scoring.types import CheckResult, ScoringInput

# Types the coverage check counts, 2 points each, capped at 8.
COVERAGE_TYPES = (
    "Product",
    "Service",
    "Offer",
    "Event",
    "FAQPage",
    "OpeningHoursSpecification",
)
COVERAGE_POINTS_PER_TYPE = 2
COVERAGE_MAX = 8

IDENTITY_TYPES = ("Organization", "LocalBusiness")

STRUCTURED_KINDS = ("jsonld", "microdata", "rdfa")


@lru_cache(maxsize=1)
def required_properties() -> dict[str, dict]:
    """The operational required-property table. See schema_required.yaml."""
    path = Path(__file__).resolve().parent.parent / "schema_required.yaml"
    return yaml.safe_load(path.read_text())["types"]


def _refs(*evidence: Evidence) -> tuple[str, ...]:
    return tuple(e.id for e in evidence)


def _type_of(evidence: Evidence) -> str:
    """The @type this evidence row describes, from its selector."""
    return (evidence.selector or "").rsplit("#", 1)[-1]


def _payload(evidence: Evidence) -> dict | None:
    try:
        parsed = json.loads(evidence.raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def check_jsonld_present(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    structured = [e for e in store.by_kind(*STRUCTURED_KINDS) if "#untyped" not in (e.selector or "")]
    if structured:
        syntaxes = sorted({e.kind for e in structured})
        return CheckResult(
            check_id="a2_structured_present",
            label="Valid schema.org structured data present",
            points_awarded=4,
            max_points=4,
            evidence_refs=_refs(*structured[:10]),
            detail=f"{len(structured)} typed entities across {', '.join(syntaxes)}.",
        )

    untyped = [e for e in store.by_kind(*STRUCTURED_KINDS)]
    return CheckResult(
        check_id="a2_structured_present",
        label="Valid schema.org structured data present",
        points_awarded=0,
        max_points=4,
        evidence_refs=_refs(*untyped[:5]),
        detail=(
            "Structured data markup exists but no node carries an @type."
            if untyped
            else "No schema.org JSON-LD, microdata or RDFa found."
        ),
    )


def check_organization_node(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    """Organization or LocalBusiness carrying name, url and address."""
    candidates = [e for e in store.by_kind(*STRUCTURED_KINDS) if _type_of(e) in IDENTITY_TYPES]

    for evidence in candidates:
        payload = _payload(evidence)
        if payload is None:
            continue
        has_name = bool(payload.get("name"))
        has_url = bool(payload.get("url"))
        has_address = bool(payload.get("address"))
        if has_name and has_url and has_address:
            return CheckResult(
                check_id="a2_organization_node",
                label="Organization/LocalBusiness with name, url and address",
                points_awarded=4,
                max_points=4,
                evidence_refs=_refs(evidence),
                detail=f"{_type_of(evidence)} node carries name, url and address.",
            )

    if candidates:
        missing_summary = []
        for evidence in candidates[:3]:
            payload = _payload(evidence) or {}
            missing = [f for f in ("name", "url", "address") if not payload.get(f)]
            missing_summary.append(f"{_type_of(evidence)} missing {missing}")
        return CheckResult(
            check_id="a2_organization_node",
            label="Organization/LocalBusiness with name, url and address",
            points_awarded=0,
            max_points=4,
            evidence_refs=_refs(*candidates[:3]),
            detail="Identity node present but incomplete: " + "; ".join(missing_summary),
        )

    return CheckResult(
        check_id="a2_organization_node",
        label="Organization/LocalBusiness with name, url and address",
        points_awarded=0,
        max_points=4,
        detail="No Organization or LocalBusiness node found.",
    )


def check_entity_coverage(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    """2 points per distinct commercial entity type, capped at 8."""
    structured = store.by_kind(*STRUCTURED_KINDS)
    found: dict[str, Evidence] = {}
    for evidence in structured:
        type_name = _type_of(evidence)
        if type_name in COVERAGE_TYPES and type_name not in found:
            found[type_name] = evidence

    points = min(len(found) * COVERAGE_POINTS_PER_TYPE, COVERAGE_MAX)

    return CheckResult(
        check_id="a2_entity_coverage",
        label=f"Entity-type coverage ({COVERAGE_POINTS_PER_TYPE} pts each, max {COVERAGE_MAX})",
        points_awarded=points,
        max_points=COVERAGE_MAX,
        evidence_refs=_refs(*found.values()),
        detail=(
            f"Found {sorted(found)} of {list(COVERAGE_TYPES)}."
            if found
            else f"None of {list(COVERAGE_TYPES)} were found."
        ),
    )


def check_required_properties(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    """Zero violations against the operational required-property table."""
    table = required_properties()
    structured = store.by_kind(*STRUCTURED_KINDS)
    checkable = [e for e in structured if _type_of(e) in table]

    if not checkable:
        return CheckResult(
            check_id="a2_required_properties",
            label="Structured data has no required-property violations",
            points_awarded=0,
            max_points=4,
            suppressed=True,
            suppressed_reason=(
                "No entities of a type covered by the required-property table were found, "
                "so there is nothing to validate."
            ),
        )

    violations: list[str] = []
    offenders: list[Evidence] = []

    for evidence in checkable:
        payload = _payload(evidence)
        if payload is None:
            continue
        type_name = _type_of(evidence)
        for prop in table[type_name].get("required", []):
            if not payload.get(prop):
                violations.append(f"{type_name} missing required property {prop!r}")
                offenders.append(evidence)

    if violations:
        unique = list(dict.fromkeys(violations))
        return CheckResult(
            check_id="a2_required_properties",
            label="Structured data has no required-property violations",
            points_awarded=0,
            max_points=4,
            evidence_refs=_refs(*offenders[:8]),
            detail=(
                f"{len(unique)} violation(s) against Wasl's operational definition "
                f"(see scoring/schema_required.yaml): " + "; ".join(unique[:6])
            ),
        )

    return CheckResult(
        check_id="a2_required_properties",
        label="Structured data has no required-property violations",
        points_awarded=4,
        max_points=4,
        evidence_refs=_refs(*checkable[:10]),
        detail=(
            f"{len(checkable)} entities validated against the operational "
            "required-property table with no violations."
        ),
    )


CHECKS = (
    check_jsonld_present,
    check_organization_node,
    check_entity_coverage,
    check_required_properties,
)


def evaluate(store: EvidenceStore, scoring_input: ScoringInput) -> tuple[CheckResult, ...]:
    return tuple(check(store, scoring_input) for check in CHECKS)
