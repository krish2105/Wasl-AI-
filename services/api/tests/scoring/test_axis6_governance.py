"""Axis 6 — Agent Governance & Safety.

Two polarities that are easy to get backwards are pinned down here: terms that
prohibit crawling score the same as terms that permit it, and injection evidence
counts against the site rather than for it.
"""

from __future__ import annotations

from tests.scoring.conftest import by_id, ev, scoring_input, store
from wasl.scoring.axes import governance


def evaluate(*evidence, **kwargs):
    return governance.evaluate(store(*evidence), scoring_input(**kwargs))


def injection(category: str, pattern: str = "ignore_previous") -> tuple[str, str]:
    return (
        f"injection#{pattern}#hidden_element",
        f"category: {category}\npattern: {pattern} (severity high)\nlocation: hidden_element",
    )


# --- ToS addresses automation (3) --------------------------------------------


def test_terms_discussing_automation_award_three() -> None:
    result = by_id(
        evaluate(ev("text", "governance#tos-addresses-automation", "no automated scraping")),
        "a6_tos_automation",
    )
    assert result.points_awarded == 3


def test_terms_prohibiting_crawling_score_the_same_as_permitting() -> None:
    """The axis measures whether the question was addressed, not the answer."""
    prohibits = by_id(
        evaluate(ev("text", "governance#tos-addresses-automation", "scraping is prohibited")),
        "a6_tos_automation",
    )
    permits = by_id(
        evaluate(ev("text", "governance#tos-addresses-automation", "automated access is permitted")),
        "a6_tos_automation",
    )
    assert prohibits.points_awarded == permits.points_awarded == 3


def test_silent_terms_award_nothing() -> None:
    result = by_id(
        evaluate(ev("text", "governance#tos-silent-on-automation", "scanned, nothing found")),
        "a6_tos_automation",
    )
    assert result.points_awarded == 0
    assert not result.suppressed


def test_unreached_terms_page_is_suppressed_not_failed() -> None:
    """Not finding the page differs from the page being silent."""
    result = by_id(evaluate(), "a6_tos_automation")
    assert result.suppressed
    assert "never read" in (result.suppressed_reason or "")


# --- rate limit headers (2) --------------------------------------------------


def test_observed_rate_limit_headers_award_two() -> None:
    result = by_id(
        evaluate(ev("header", "header#rate-limit", "retry-after: 120")),
        "a6_rate_limit_headers",
    )
    assert result.points_awarded == 2


def test_no_headers_awards_nothing_and_states_we_did_not_probe() -> None:
    result = by_id(evaluate(), "a6_rate_limit_headers")
    assert result.points_awarded == 0
    assert "does not send bursts" in result.detail


# --- machine auth documented (3) ---------------------------------------------


def test_documented_machine_auth_awards_three() -> None:
    result = by_id(
        evaluate(ev("text", "governance#machine-auth-documented", "Use an API key header")),
        "a6_machine_auth",
    )
    assert result.points_awarded == 3


def test_undocumented_auth_surface_awards_nothing() -> None:
    result = by_id(evaluate(ev("header", "header#auth", "www-authenticate: Basic")), "a6_machine_auth")
    assert result.points_awarded == 0
    assert "not usable" in result.detail


def test_no_auth_surface_awards_nothing() -> None:
    assert by_id(evaluate(), "a6_machine_auth").points_awarded == 0


# --- no injection detected (2) -----------------------------------------------


def test_a_scanned_clean_page_awards_two() -> None:
    result = by_id(evaluate(ev("injection", "injection#clean", "scanned, nothing found")), "a6_no_injection")
    assert result.points_awarded == 2


def test_injection_findings_award_nothing() -> None:
    """Evidence on this check counts against the site."""
    selector, raw = injection("instruction_override")
    result = by_id(evaluate(ev("injection", selector, raw)), "a6_no_injection")
    assert result.points_awarded == 0
    assert result.evidence_refs


def test_never_scanned_is_suppressed_not_awarded() -> None:
    """Cleanliness cannot be asserted about a page nobody looked at."""
    result = by_id(evaluate(), "a6_no_injection")
    assert result.suppressed
    assert result.points_awarded == 0


def test_findings_report_their_categories() -> None:
    selector, raw = injection("ranking_manipulation", "ranking_manipulation")
    result = by_id(evaluate(ev("injection", selector, raw)), "a6_no_injection")
    assert "ranking_manipulation" in result.detail


def test_report_notes_findings_may_be_user_generated() -> None:
    """A review site is not the author of every string on its own pages."""
    selector, raw = injection("instruction_override")
    result = by_id(evaluate(ev("injection", selector, raw)), "a6_no_injection")
    assert "user-generated" in result.detail


# --- axis totals -------------------------------------------------------------


def test_axis_sums_to_ten() -> None:
    assert sum(c.max_points for c in evaluate()) == 10
