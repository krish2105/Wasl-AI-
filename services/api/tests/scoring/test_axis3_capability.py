"""Axis 3 — Capability Exposure. The heaviest axis, and the one with the sharpest
hard negatives: a marketing page about an API must never score like an API.
"""

from __future__ import annotations

from tests.scoring.conftest import by_id, ev, scoring_input, store
from wasl.scoring.axes import capability


def evaluate(*evidence, **kwargs):
    return capability.evaluate(store(*evidence), scoring_input(**kwargs))


def url_pattern(pattern: str, count: int) -> str:
    return f"Stable URL pattern {pattern} seen on {count} distinct link(s).\nhttps://example.com/x"


def form(method: str, purpose: str, coverage: int = 100, named: int = 3) -> tuple[str, str]:
    selector = f"form#f#{method}#{purpose}"
    raw = (
        f"{method.upper()} form, purpose={purpose}, action=/x\n"
        f"4 fields, {named} named, 4 labelled ({coverage}% label coverage)\n"
    )
    return selector, raw


# --- OpenAPI spec (6) --------------------------------------------------------


def test_a_real_spec_awards_six() -> None:
    result = by_id(evaluate(ev("openapi", "openapi#spec", "OpenAPI 3.0.0")), "a3_openapi_spec")
    assert result.points_awarded == 6


def test_html_at_a_spec_path_awards_nothing() -> None:
    """The hard negative: HTTP 200 is not a spec."""
    result = by_id(evaluate(ev("openapi", "openapi#not-a-spec", "html")), "a3_openapi_spec")
    assert result.points_awarded == 0
    assert "not an OpenAPI document" in result.detail


def test_no_spec_awards_nothing() -> None:
    assert by_id(evaluate(ev("openapi", "openapi#no-spec", "none")), "a3_openapi_spec").points_awarded == 0


# --- documented API (3) ------------------------------------------------------


def test_api_docs_link_awards_three() -> None:
    result = by_id(
        evaluate(ev("openapi", "a[href=/api-reference]", "API/developer link: API -> /api-reference")),
        "a3_documented_api",
    )
    assert result.points_awarded == 3


def test_docs_without_a_spec_never_earn_the_spec_points() -> None:
    """The whole distinction this axis draws: 3 for prose, 6 only for a spec."""
    checks = evaluate(ev("openapi", "a[href=/api]", "API/developer link: API -> /api"))
    assert by_id(checks, "a3_documented_api").points_awarded == 3
    assert by_id(checks, "a3_openapi_spec").points_awarded == 0


def test_no_api_documentation_awards_nothing() -> None:
    assert by_id(evaluate(), "a3_documented_api").points_awarded == 0


# --- agent manifest (6) ------------------------------------------------------


def test_agent_manifest_awards_six() -> None:
    result = by_id(
        evaluate(ev("wellknown", "wellknown/.well-known/mcp.json#manifest", "tools")),
        "a3_agent_manifest",
    )
    assert result.points_awarded == 6


def test_non_manifest_at_a_wellknown_path_awards_nothing() -> None:
    result = by_id(
        evaluate(ev("wellknown", "wellknown/.well-known/mcp.json#not-a-manifest", "shell")),
        "a3_agent_manifest",
    )
    assert result.points_awarded == 0


# --- stable discovery URLs (5) -----------------------------------------------


def test_two_strong_url_patterns_award_five() -> None:
    result = by_id(
        evaluate(
            ev("identifier", "url-pattern#/product/{id}", url_pattern("/product/{id}", 6)),
            ev("identifier", "url-pattern#/category/{slug}", url_pattern("/category/{slug}", 4)),
        ),
        "a3_stable_discovery",
    )
    assert result.points_awarded == 5


def test_one_pattern_alone_is_not_enough() -> None:
    """A single URL shape could be a coincidence of one page's markup."""
    result = by_id(
        evaluate(ev("identifier", "url-pattern#/product/{id}", url_pattern("/product/{id}", 6))),
        "a3_stable_discovery",
    )
    assert result.points_awarded == 0


def test_a_pattern_seen_once_does_not_qualify() -> None:
    result = by_id(
        evaluate(
            ev("identifier", "url-pattern#/a/{id}", url_pattern("/a/{id}", 1)),
            ev("identifier", "url-pattern#/b/{id}", url_pattern("/b/{id}", 1)),
        ),
        "a3_stable_discovery",
    )
    assert result.points_awarded == 0


def test_a_get_search_form_alone_awards_five() -> None:
    """A GET form is an explicit invitation to construct the URL."""
    selector, raw = form("get", "search")
    result = by_id(evaluate(ev("form", selector, raw)), "a3_stable_discovery")
    assert result.points_awarded == 5


def test_a_post_form_does_not_qualify() -> None:
    selector, raw = form("post", "search")
    result = by_id(evaluate(ev("form", selector, raw)), "a3_stable_discovery")
    assert result.points_awarded == 0


# --- contact capability (3) --------------------------------------------------


def test_labelled_contact_form_awards_three() -> None:
    selector, raw = form("post", "contact", coverage=100)
    result = by_id(evaluate(ev("form", selector, raw)), "a3_contact_capability")
    assert result.points_awarded == 3


def test_unlabelled_contact_form_awards_nothing() -> None:
    selector, raw = form("post", "contact", coverage=0, named=0)
    result = by_id(evaluate(ev("form", selector, raw)), "a3_contact_capability")
    assert result.points_awarded == 0


def test_no_contact_form_awards_nothing() -> None:
    assert by_id(evaluate(), "a3_contact_capability").points_awarded == 0


# --- pricing without login (2) -----------------------------------------------


def test_public_pricing_awards_two() -> None:
    result = by_id(
        evaluate(ev("text", "pricing#structured-price", "Offer.price = 14.50")),
        "a3_pricing_without_login",
    )
    assert result.points_awarded == 2


def test_gated_pricing_awards_nothing() -> None:
    result = by_id(
        evaluate(
            ev("text", "pricing#rendered-price", "AED 14.50"),
            ev("header", "header#interstitial", "cf-challenge"),
        ),
        "a3_pricing_without_login",
    )
    assert result.points_awarded == 0
    assert "gated" in result.detail


def test_no_pricing_at_all_awards_nothing() -> None:
    assert by_id(evaluate(), "a3_pricing_without_login").points_awarded == 0


# --- axis totals -------------------------------------------------------------


def test_axis_sums_to_twenty_five() -> None:
    assert sum(c.max_points for c in evaluate()) == 25
