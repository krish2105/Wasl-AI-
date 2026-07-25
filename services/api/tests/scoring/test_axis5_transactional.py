"""Axis 5 — Transactional Integrity."""

from __future__ import annotations

from tests.scoring.conftest import by_id, ev, scoring_input, store
from wasl.scoring.axes import transactional


def evaluate(*evidence, **kwargs):
    return transactional.evaluate(store(*evidence), scoring_input(**kwargs))


def form_evidence(coverage: int, purpose: str = "contact") -> tuple[str, str]:
    return (
        f"form#f#post#{purpose}",
        f"POST form, purpose={purpose}, action=/x\n4 fields, 4 named, "
        f"{coverage // 25} labelled ({coverage}% label coverage)\n",
    )


# --- stable identifiers (5) --------------------------------------------------


def test_structured_identifiers_award_five() -> None:
    result = by_id(
        evaluate(ev("identifier", "jsonld#Product.sku", "Product.sku = NSC-1")),
        "a5_stable_identifiers",
    )
    assert result.points_awarded == 5


def test_url_inferred_identifiers_award_three_not_five() -> None:
    """Inference is weaker than declaration, and the score should say so."""
    result = by_id(
        evaluate(ev("identifier", "url-pattern#/product/{id}", "seen on 6 distinct link(s)")),
        "a5_stable_identifiers",
    )
    assert result.points_awarded == 3
    assert "weaker than declaration" in result.detail


def test_no_identifiers_award_nothing() -> None:
    assert by_id(evaluate(), "a5_stable_identifiers").points_awarded == 0


# --- structured pricing (4) --------------------------------------------------


def test_structured_price_and_availability_award_four() -> None:
    result = by_id(
        evaluate(
            ev("text", "pricing#structured-price", "Offer.price = 14.50"),
            ev("text", "pricing#structured-availability", "Offer.availability = InStock"),
        ),
        "a5_structured_pricing",
    )
    assert result.points_awarded == 4


def test_price_only_awards_partial() -> None:
    result = by_id(
        evaluate(ev("text", "pricing#structured-price", "Offer.price = 14.50")),
        "a5_structured_pricing",
    )
    assert result.points_awarded == 2


def test_rendered_text_only_awards_nothing() -> None:
    result = by_id(
        evaluate(ev("text", "pricing#rendered-price", "AED 14.50")),
        "a5_structured_pricing",
    )
    assert result.points_awarded == 0
    assert "parse prose" in result.detail


def test_a_site_that_sells_nothing_is_suppressed_not_failed() -> None:
    """Plenty of legitimate sites have no prices. That is not a failing."""
    result = by_id(evaluate(), "a5_structured_pricing")
    assert result.suppressed
    assert result.counted_max == 0


# --- form labelling (3) ------------------------------------------------------


def test_fully_labelled_forms_award_three() -> None:
    selector, raw = form_evidence(100)
    assert by_id(evaluate(ev("form", selector, raw)), "a5_form_labelling").points_awarded == 3


def test_exactly_at_the_threshold_passes() -> None:
    selector, raw = form_evidence(90)
    assert by_id(evaluate(ev("form", selector, raw)), "a5_form_labelling").points_awarded == 3


def test_just_below_the_threshold_fails() -> None:
    selector, raw = form_evidence(89)
    assert by_id(evaluate(ev("form", selector, raw)), "a5_form_labelling").points_awarded == 0


def test_no_forms_is_suppressed() -> None:
    result = by_id(evaluate(), "a5_form_labelling")
    assert result.suppressed


# --- interstitials (3) -------------------------------------------------------


def test_ungated_site_awards_three() -> None:
    result = by_id(
        evaluate(ev("header", "header#no-interstitial", "checked, none found")),
        "a5_no_interstitials",
    )
    assert result.points_awarded == 3
    assert result.evidence_refs, "an award for an absence still needs a receipt"


def test_never_checking_for_gates_is_suppressed_not_awarded() -> None:
    """'Not gated' is a claim. It needs a page that was actually checked."""
    result = by_id(evaluate(), "a5_no_interstitials")
    assert result.suppressed
    assert result.points_awarded == 0


def test_captcha_gate_awards_nothing() -> None:
    result = by_id(
        evaluate(ev("header", "header#interstitial", "recaptcha detected")),
        "a5_no_interstitials",
    )
    assert result.points_awarded == 0


def test_the_report_does_not_call_blocking_wrong() -> None:
    """Anti-abuse is a legitimate choice; we record the consequence, not a judgement."""
    result = by_id(
        evaluate(ev("header", "header#interstitial", "cf-challenge")),
        "a5_no_interstitials",
    )
    assert "legitimate anti-abuse choice" in result.detail


# --- axis totals -------------------------------------------------------------


def test_axis_sums_to_fifteen() -> None:
    assert sum(c.max_points for c in evaluate()) == 15
