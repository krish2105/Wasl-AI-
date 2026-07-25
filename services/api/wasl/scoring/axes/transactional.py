"""Axis 5 — Transactional Integrity (15 points, 4 checks).

Could an agent complete a real task here, or only browse?

The distinction this axis draws is between *readable* and *transactable*. A site
can be beautifully structured and still impossible to act on if nothing has a
stable name. "The third card on the listings page" is not something an agent can
put in a workflow; "listing 884213" is.
"""

from __future__ import annotations

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.scoring.types import CheckResult, ScoringInput

FORM_LABEL_THRESHOLD = 0.90


def _refs(*evidence: Evidence) -> tuple[str, ...]:
    return tuple(e.id for e in evidence)


def check_stable_identifiers(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    structured = [
        e for e in store.by_kind("identifier") if (e.selector or "").startswith("jsonld#")
    ]
    url_based = [
        e
        for e in store.by_kind("identifier")
        if (e.selector or "").startswith(("url-pattern#", "url-query#"))
    ]

    if structured:
        return CheckResult(
            check_id="a5_stable_identifiers",
            label="Stable machine identifiers present (SKU, product/listing ID)",
            points_awarded=5,
            max_points=5,
            evidence_refs=_refs(*structured[:8]),
            detail=(
                f"{len(structured)} identifier(s) in structured markup — unambiguous and "
                "quotable back to the site."
            ),
        )

    if url_based:
        # Inferred rather than declared, so it earns most of the points but not all.
        return CheckResult(
            check_id="a5_stable_identifiers",
            label="Stable machine identifiers present (SKU, product/listing ID)",
            points_awarded=3,
            max_points=5,
            evidence_refs=_refs(*url_based[:8]),
            detail=(
                f"{len(url_based)} stable identifier pattern(s) inferred from URL structure, "
                "but none declared in markup. Inference is weaker than declaration."
            ),
        )

    return CheckResult(
        check_id="a5_stable_identifiers",
        label="Stable machine identifiers present (SKU, product/listing ID)",
        points_awarded=0,
        max_points=5,
        detail="No stable identifiers found in markup or URL structure.",
    )


def check_structured_pricing(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    """Price AND availability in structured markup, not only rendered text."""
    structured_price = [
        e for e in store.by_kind("text") if e.selector == "pricing#structured-price"
    ]
    structured_availability = [
        e for e in store.by_kind("text") if e.selector == "pricing#structured-availability"
    ]
    rendered = [
        e for e in store.by_kind("text") if (e.selector or "").startswith("pricing#rendered")
    ]

    if structured_price and structured_availability:
        return CheckResult(
            check_id="a5_structured_pricing",
            label="Prices and availability in structured markup, not only rendered text",
            points_awarded=4,
            max_points=4,
            evidence_refs=_refs(*structured_price[:4], *structured_availability[:4]),
            detail="Both price and availability are machine-readable.",
        )

    if structured_price or structured_availability:
        return CheckResult(
            check_id="a5_structured_pricing",
            label="Prices and availability in structured markup, not only rendered text",
            points_awarded=2,
            max_points=4,
            evidence_refs=_refs(*structured_price[:4], *structured_availability[:4]),
            detail=(
                f"{'Price' if structured_price else 'Availability'} is structured; the other "
                "is only in rendered text."
            ),
        )

    if rendered:
        return CheckResult(
            check_id="a5_structured_pricing",
            label="Prices and availability in structured markup, not only rendered text",
            points_awarded=0,
            max_points=4,
            evidence_refs=_refs(*rendered[:6]),
            detail=(
                "Price and availability appear only as rendered text. An agent must parse "
                "prose and hope it guessed the currency correctly."
            ),
        )

    return CheckResult(
        check_id="a5_structured_pricing",
        label="Prices and availability in structured markup, not only rendered text",
        points_awarded=0,
        max_points=4,
        suppressed=True,
        suppressed_reason=(
            "No pricing or availability information of any kind was found, so there is "
            "nothing to judge. Many legitimate sites do not sell anything."
        ),
    )


def _label_coverage(raw: str) -> float | None:
    if "% label coverage" not in raw:
        return None
    try:
        return int(raw.split("% label coverage")[0].rsplit("(", 1)[-1]) / 100
    except (IndexError, ValueError):
        return None


def check_form_labelling(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    forms = store.by_kind("form")
    if not forms:
        return CheckResult(
            check_id="a5_form_labelling",
            label=f"Forms have name, id and label on ≥{FORM_LABEL_THRESHOLD:.0%} of inputs",
            points_awarded=0,
            max_points=3,
            suppressed=True,
            suppressed_reason="No forms were found, so there is nothing to evaluate.",
        )

    coverages = [(e, _label_coverage(e.raw)) for e in forms]
    measured = [(e, c) for e, c in coverages if c is not None]
    if not measured:
        return CheckResult(
            check_id="a5_form_labelling",
            label=f"Forms have name, id and label on ≥{FORM_LABEL_THRESHOLD:.0%} of inputs",
            points_awarded=0,
            max_points=3,
            suppressed=True,
            suppressed_reason="Forms were found but no label coverage could be measured.",
        )

    average = sum(c for _, c in measured) / len(measured)
    passed = average >= FORM_LABEL_THRESHOLD

    return CheckResult(
        check_id="a5_form_labelling",
        label=f"Forms have name, id and label on ≥{FORM_LABEL_THRESHOLD:.0%} of inputs",
        points_awarded=3 if passed else 0,
        max_points=3,
        evidence_refs=_refs(*[e for e, _ in measured[:6]]),
        detail=(
            f"Mean label coverage across {len(measured)} form(s) is {average:.0%}; "
            f"threshold is {FORM_LABEL_THRESHOLD:.0%}."
        ),
    )


def check_no_interstitials(store: EvidenceStore, scoring_input: ScoringInput) -> CheckResult:
    gated = [e for e in store.by_kind("header") if e.selector == "header#interstitial"]
    clean = [e for e in store.by_kind("header") if e.selector == "header#no-interstitial"]

    if not gated and clean:
        return CheckResult(
            check_id="a5_no_interstitials",
            label="Primary discovery paths are not gated behind CAPTCHA/interstitials",
            points_awarded=3,
            max_points=3,
            evidence_refs=_refs(*clean[:6]),
            detail=(
                f"No CAPTCHA, bot challenge or blocking interstitial was encountered across "
                f"{len(clean)} checked page(s)."
            ),
        )

    if not gated and not clean:
        # Nothing was checked, so "not gated" is not a claim we can make.
        return CheckResult(
            check_id="a5_no_interstitials",
            label="Primary discovery paths are not gated behind CAPTCHA/interstitials",
            points_awarded=0,
            max_points=3,
            suppressed=True,
            suppressed_reason="No page was checked for interstitials.",
        )

    return CheckResult(
        check_id="a5_no_interstitials",
        label="Primary discovery paths are not gated behind CAPTCHA/interstitials",
        points_awarded=0,
        max_points=3,
        evidence_refs=_refs(*gated[:6]),
        detail=(
            f"{len(gated)} page(s) returned a challenge or interstitial. Note this is a "
            "legitimate anti-abuse choice by the site — it is recorded because it makes "
            "the site unusable to agents, not because it is wrong."
        ),
    )


CHECKS = (
    check_stable_identifiers,
    check_structured_pricing,
    check_form_labelling,
    check_no_interstitials,
)


def evaluate(store: EvidenceStore, scoring_input: ScoringInput) -> tuple[CheckResult, ...]:
    return tuple(check(store, scoring_input) for check in CHECKS)
