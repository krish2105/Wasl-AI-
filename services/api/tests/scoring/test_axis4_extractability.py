"""Axis 4 — Content Extractability.

The suppression behaviour is the important thing here. A degraded capture cannot
measure the rendering delta, and scoring that unknown as zero would punish sites
for a limitation of our own infrastructure.
"""

from __future__ import annotations

from tests.scoring.conftest import by_id, ev, scoring_input, store
from wasl.scoring.axes import extractability


def evaluate(*evidence, **kwargs):
    return extractability.evaluate(store(*evidence), scoring_input(**kwargs))


def delta(ratio: float, url: str = "https://example.com/page") -> str:
    return (
        f"pre-JS meaningful text: 1000 chars\npost-JS meaningful text: {int(1000 / max(ratio, 0.001))} chars\n"
        f"ratio: {ratio:.3f}\nverdict: test fixture"
    )


def landmarks(main: int = 1, nav: int = 1) -> str:
    return f"Landmark elements: <main>={main}, <article>=2, <nav>={nav}, role=main:0, role=navigation:0"


def headings(h1_count: int = 1, skips: str = "none") -> str:
    return f"8 headings, {h1_count} <h1>.\nh1 text: ['Title']\nhierarchy skips: {skips}"


# --- server-rendered content (5) ---------------------------------------------


def test_server_rendered_site_awards_five() -> None:
    result = by_id(evaluate(ev("rendering", "rendering#delta", delta(0.95))), "a4_server_rendered")
    assert result.points_awarded == 5


def test_hydration_only_site_awards_nothing() -> None:
    result = by_id(evaluate(ev("rendering", "rendering#delta", delta(0.02))), "a4_server_rendered")
    assert result.points_awarded == 0
    assert "only a fragment" in result.detail


def test_exactly_at_the_threshold_passes() -> None:
    result = by_id(evaluate(ev("rendering", "rendering#delta", delta(0.5))), "a4_server_rendered")
    assert result.points_awarded == 5


def test_degraded_capture_suppresses_rather_than_fails() -> None:
    """'We could not look' must not be scored as 'we looked and found nothing'."""
    result = by_id(
        evaluate(ev("rendering", "rendering#unavailable", "no browser"), degraded=True),
        "a4_server_rendered",
    )
    assert result.suppressed
    assert result.points_awarded == 0
    assert result.counted_max == 0
    assert "Unknown is not the same as zero" in (result.suppressed_reason or "")


def test_ratio_is_averaged_across_pages() -> None:
    result = by_id(
        evaluate(
            ev("rendering", "rendering#delta", delta(0.9), url="https://example.com/a"),
            ev("rendering", "rendering#delta", delta(0.1), url="https://example.com/b"),
        ),
        "a4_server_rendered",
    )
    # Mean of 0.9 and 0.1 is 0.5, exactly the threshold.
    assert result.points_awarded == 5


# --- semantic HTML (4) -------------------------------------------------------


def test_full_semantics_award_four() -> None:
    result = by_id(
        evaluate(
            ev("dom", "semantics#landmarks", landmarks()),
            ev("dom", "semantics#headings", headings()),
        ),
        "a4_semantic_html",
    )
    assert result.points_awarded == 4


def test_div_soup_awards_nothing() -> None:
    result = by_id(
        evaluate(
            ev("dom", "semantics#landmarks", landmarks(main=0, nav=0)),
            ev("dom", "semantics#headings", headings(h1_count=0, skips="h1 -> h3")),
        ),
        "a4_semantic_html",
    )
    assert result.points_awarded == 0


def test_partial_semantics_award_partial_points() -> None:
    result = by_id(
        evaluate(
            ev("dom", "semantics#landmarks", landmarks(main=1, nav=0)),
            ev("dom", "semantics#headings", headings(h1_count=1, skips="h1 -> h3")),
        ),
        "a4_semantic_html",
    )
    assert 0 < result.points_awarded < 4


def test_semantics_are_suppressed_when_nothing_was_read() -> None:
    assert by_id(evaluate(), "a4_semantic_html").suppressed


# --- text not locked in images (3) -------------------------------------------


def test_text_dominant_page_awards_three() -> None:
    result = by_id(
        evaluate(ev("media", "media#text-image-balance", "verdict: text-dominant or adequately described")),
        "a4_text_in_images",
    )
    assert result.points_awarded == 3


def test_image_dominant_page_awards_nothing() -> None:
    result = by_id(
        evaluate(ev("media", "media#text-image-balance", "verdict: image-dominant")),
        "a4_text_in_images",
    )
    assert result.points_awarded == 0


def test_media_check_is_suppressed_with_no_reading() -> None:
    assert by_id(evaluate(), "a4_text_in_images").suppressed


# --- crawlable pagination (3) ------------------------------------------------


def test_crawlable_pagination_awards_three() -> None:
    result = by_id(
        evaluate(ev("pagination", "pagination#crawlable-urls", "4 crawlable URLs")),
        "a4_crawlable_pagination",
    )
    assert result.points_awarded == 3


def test_rel_next_alone_awards_three() -> None:
    result = by_id(evaluate(ev("pagination", "pagination#rel", "rel=next")), "a4_crawlable_pagination")
    assert result.points_awarded == 3


def test_infinite_scroll_only_awards_nothing() -> None:
    result = by_id(
        evaluate(
            ev("pagination", "pagination#infinite-scroll", "marker found. may be unreachable without a browser")
        ),
        "a4_crawlable_pagination",
    )
    assert result.points_awarded == 0


def test_no_pagination_awards_nothing_but_is_not_suppressed() -> None:
    """A site with no listings genuinely has no pagination; that is a real zero."""
    result = by_id(evaluate(ev("pagination", "pagination#none", "none")), "a4_crawlable_pagination")
    assert result.points_awarded == 0
    assert not result.suppressed


# --- axis totals -------------------------------------------------------------


def test_axis_sums_to_fifteen() -> None:
    assert sum(c.max_points for c in evaluate()) == 15


def test_degraded_axis_reduces_its_counted_maximum() -> None:
    checks = evaluate(ev("rendering", "rendering#unavailable", "no browser"), degraded=True)
    assert sum(c.max_points for c in checks) == 15
    assert sum(c.counted_max for c in checks) < 15
