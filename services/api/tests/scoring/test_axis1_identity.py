"""Axis 1 — Machine-Readable Identity. A passing and a failing case per check."""

from __future__ import annotations

from tests.scoring.conftest import by_id, ev, scoring_input, store
from wasl.scoring.axes import identity


def evaluate(*evidence, **kwargs):
    return identity.evaluate(store(*evidence), scoring_input(**kwargs))


# --- robots.txt present and parseable (2) ------------------------------------


def test_robots_present_and_parseable_awards_two() -> None:
    result = by_id(evaluate(ev("robots", "robots.txt", "User-agent: *")), "a1_robots_present")
    assert result.points_awarded == 2
    assert result.evidence_refs


def test_robots_absent_awards_nothing() -> None:
    result = by_id(evaluate(ev("robots", "robots.txt#absent", "not found")), "a1_robots_present")
    assert result.points_awarded == 0


def test_robots_present_but_unparseable_awards_nothing() -> None:
    result = by_id(
        evaluate(
            ev("robots", "robots.txt", "garbage"),
            ev("robots", "robots.txt#unparseable", "could not parse"),
        ),
        "a1_robots_present",
    )
    assert result.points_awarded == 0
    assert "could not be parsed" in result.detail


# --- AI agent stanza (3) -----------------------------------------------------


def test_ai_agent_stanza_awards_three() -> None:
    result = by_id(
        evaluate(ev("robots", "robots.txt#user-agent:GPTBot", "User-agent: GPTBot\nAllow: /")),
        "a1_robots_agent_stanza",
    )
    assert result.points_awarded == 3


def test_a_disallowing_stanza_scores_identically() -> None:
    """Clarity is the signal. A site is never penalised for saying no."""
    allowing = by_id(
        evaluate(ev("robots", "robots.txt#user-agent:GPTBot", "User-agent: GPTBot\nAllow: /")),
        "a1_robots_agent_stanza",
    )
    disallowing = by_id(
        evaluate(ev("robots", "robots.txt#user-agent:GPTBot", "User-agent: GPTBot\nDisallow: /")),
        "a1_robots_agent_stanza",
    )
    assert allowing.points_awarded == disallowing.points_awarded == 3


def test_no_ai_stanza_awards_nothing() -> None:
    result = by_id(evaluate(ev("robots", "robots.txt", "User-agent: *")), "a1_robots_agent_stanza")
    assert result.points_awarded == 0


# --- sitemap (3) -------------------------------------------------------------


def test_reachable_sitemap_awards_three() -> None:
    result = by_id(evaluate(ev("sitemap", "sitemap#present", "12 <loc> entries")), "a1_sitemap")
    assert result.points_awarded == 3


def test_declared_but_unreachable_sitemap_awards_nothing() -> None:
    result = by_id(evaluate(ev("sitemap", "sitemap#unreachable", "HTTP 404")), "a1_sitemap")
    assert result.points_awarded == 0
    assert "could not be retrieved" in result.detail


def test_absent_sitemap_awards_nothing() -> None:
    assert by_id(evaluate(ev("sitemap", "sitemap#absent", "none")), "a1_sitemap").points_awarded == 0


# --- llms.txt (4) ------------------------------------------------------------


def test_real_llms_txt_awards_four() -> None:
    result = by_id(evaluate(ev("llmstxt", "llms.txt#present", "1 H1, 4 links")), "a1_llms_txt")
    assert result.points_awarded == 4


def test_spa_shell_at_llms_txt_awards_nothing() -> None:
    """The most valuable single check must not be won by having a catch-all route."""
    result = by_id(evaluate(ev("llmstxt", "llms.txt#not-markdown", "html shell")), "a1_llms_txt")
    assert result.points_awarded == 0
    assert "HTML shell" in result.detail


def test_absent_llms_txt_awards_nothing() -> None:
    assert by_id(evaluate(ev("llmstxt", "llms.txt#absent", "404")), "a1_llms_txt").points_awarded == 0


# --- canonical coverage (3) --------------------------------------------------


def test_canonical_on_every_page_awards_three() -> None:
    evidence = [
        ev("link", "link[rel=canonical]", "<link>", url=f"https://example.com/{i}")
        for i in range(10)
    ]
    result = by_id(evaluate(*evidence, pages_ok=10), "a1_canonical_coverage")
    assert result.points_awarded == 3


def test_canonical_at_exactly_the_threshold_passes() -> None:
    """80% is the stated threshold, so 80% must pass."""
    evidence = [
        ev("link", "link[rel=canonical]", "<link>", url=f"https://example.com/{i}")
        for i in range(8)
    ]
    result = by_id(evaluate(*evidence, pages_ok=10), "a1_canonical_coverage")
    assert result.points_awarded == 3


def test_canonical_just_below_the_threshold_fails() -> None:
    evidence = [
        ev("link", "link[rel=canonical]", "<link>", url=f"https://example.com/{i}")
        for i in range(7)
    ]
    result = by_id(evaluate(*evidence, pages_ok=10), "a1_canonical_coverage")
    assert result.points_awarded == 0
    assert "70%" in result.detail


def test_canonical_check_is_suppressed_when_nothing_was_crawled() -> None:
    result = by_id(evaluate(pages_ok=0, pages_crawled=0), "a1_canonical_coverage")
    assert result.suppressed
    assert result.counted_max == 0


# --- axis totals -------------------------------------------------------------


def test_axis_sums_to_fifteen() -> None:
    assert sum(c.max_points for c in evaluate()) == 15


def test_a_perfect_axis_awards_all_fifteen() -> None:
    checks = evaluate(
        ev("robots", "robots.txt", "User-agent: *"),
        ev("robots", "robots.txt#user-agent:ClaudeBot", "Allow: /"),
        ev("sitemap", "sitemap#present", "20 entries"),
        ev("llmstxt", "llms.txt#present", "valid"),
        *[ev("link", "link[rel=canonical]", "<link>", url=f"https://example.com/{i}") for i in range(10)],
        pages_ok=10,
    )
    assert sum(c.points_awarded for c in checks) == 15
