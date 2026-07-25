"""Axis 2 — Structured Data Coverage."""

from __future__ import annotations

import json

from tests.scoring.conftest import by_id, ev, scoring_input, store
from wasl.scoring.axes import structured_data


def evaluate(*evidence, **kwargs):
    return structured_data.evaluate(store(*evidence), scoring_input(**kwargs))


def node(type_name: str, **props) -> str:
    return json.dumps({"@type": type_name, **props})


# --- structured data present (4) ---------------------------------------------


def test_typed_jsonld_awards_four() -> None:
    result = by_id(
        evaluate(ev("jsonld", "json-ld#Product", node("Product", name="Widget"))),
        "a2_structured_present",
    )
    assert result.points_awarded == 4


def test_untyped_markup_awards_nothing() -> None:
    result = by_id(evaluate(ev("jsonld", "json-ld#untyped", "{}")), "a2_structured_present")
    assert result.points_awarded == 0
    assert "no node carries an @type" in result.detail


def test_no_structured_data_awards_nothing() -> None:
    assert by_id(evaluate(), "a2_structured_present").points_awarded == 0


def test_microdata_counts_as_structured_data() -> None:
    """All three syntaxes are equivalent to a machine reader."""
    result = by_id(
        evaluate(ev("microdata", "microdata#Product", node("Product", name="W"))),
        "a2_structured_present",
    )
    assert result.points_awarded == 4


# --- organization node (4) ---------------------------------------------------


def test_complete_organization_awards_four() -> None:
    result = by_id(
        evaluate(
            ev(
                "jsonld",
                "json-ld#Organization",
                node("Organization", name="Acme", url="https://acme.example", address={"@type": "PostalAddress"}),
            )
        ),
        "a2_organization_node",
    )
    assert result.points_awarded == 4


def test_organization_missing_address_awards_nothing() -> None:
    result = by_id(
        evaluate(ev("jsonld", "json-ld#Organization", node("Organization", name="Acme", url="https://a.example"))),
        "a2_organization_node",
    )
    assert result.points_awarded == 0
    assert "address" in result.detail


def test_local_business_also_satisfies_the_check() -> None:
    result = by_id(
        evaluate(
            ev(
                "jsonld",
                "json-ld#LocalBusiness",
                node("LocalBusiness", name="Shop", url="https://s.example", address={"@type": "PostalAddress"}),
            )
        ),
        "a2_organization_node",
    )
    assert result.points_awarded == 4


def test_no_identity_node_awards_nothing() -> None:
    result = by_id(evaluate(ev("jsonld", "json-ld#Product", node("Product", name="W"))), "a2_organization_node")
    assert result.points_awarded == 0


# --- entity coverage (2 each, max 8) -----------------------------------------


def test_each_entity_type_is_worth_two() -> None:
    result = by_id(
        evaluate(
            ev("jsonld", "json-ld#Product", node("Product", name="W")),
            ev("jsonld", "json-ld#Offer", node("Offer", price="1")),
        ),
        "a2_entity_coverage",
    )
    assert result.points_awarded == 4


def test_entity_coverage_is_capped_at_eight() -> None:
    """Six tracked types at 2 points each would be 12; the cap is 8."""
    evidence = [
        ev("jsonld", f"json-ld#{t}", node(t))
        for t in ("Product", "Service", "Offer", "Event", "FAQPage", "OpeningHoursSpecification")
    ]
    result = by_id(evaluate(*evidence), "a2_entity_coverage")
    assert result.points_awarded == 8
    assert result.max_points == 8


def test_duplicate_types_across_pages_count_once() -> None:
    result = by_id(
        evaluate(
            ev("jsonld", "json-ld#Product", node("Product", name="A"), url="https://example.com/1"),
            ev("jsonld", "json-ld#Product", node("Product", name="B"), url="https://example.com/2"),
        ),
        "a2_entity_coverage",
    )
    assert result.points_awarded == 2


def test_untracked_types_earn_nothing() -> None:
    result = by_id(evaluate(ev("jsonld", "json-ld#BreadcrumbList", node("BreadcrumbList"))), "a2_entity_coverage")
    assert result.points_awarded == 0


# --- required properties (4) -------------------------------------------------


def test_complete_entities_award_four() -> None:
    result = by_id(
        evaluate(
            ev("jsonld", "json-ld#Product", node("Product", name="Widget")),
            ev("jsonld", "json-ld#Offer", node("Offer", price="14.50", priceCurrency="AED")),
        ),
        "a2_required_properties",
    )
    assert result.points_awarded == 4


def test_offer_without_a_currency_is_a_violation() -> None:
    """The most common real-world violation: a number with no unit."""
    result = by_id(
        evaluate(ev("jsonld", "json-ld#Offer", node("Offer", price="1200"))),
        "a2_required_properties",
    )
    assert result.points_awarded == 0
    assert "priceCurrency" in result.detail


def test_product_without_a_name_is_a_violation() -> None:
    result = by_id(
        evaluate(ev("jsonld", "json-ld#Product", node("Product", sku="X1"))),
        "a2_required_properties",
    )
    assert result.points_awarded == 0


def test_check_is_suppressed_when_no_covered_types_exist() -> None:
    """Nothing to validate is not the same as failing validation."""
    result = by_id(evaluate(ev("jsonld", "json-ld#WebPage", node("WebPage"))), "a2_required_properties")
    assert result.suppressed
    assert result.counted_max == 0


def test_postal_address_does_not_require_a_postcode() -> None:
    """Requiring one would systematically penalise correct UAE addresses."""
    table = structured_data.required_properties()
    assert "postalCode" not in table["PostalAddress"]["required"]
    assert "postalCode" in table["PostalAddress"]["recommended"]


# --- axis totals -------------------------------------------------------------


def test_axis_sums_to_twenty() -> None:
    assert sum(c.max_points for c in evaluate()) == 20
