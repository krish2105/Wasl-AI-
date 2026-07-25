"""The rubric end to end: fixtures in, WARI score out.

The test that matters most is `test_the_rubric_discriminates`. A scoring system
that produces plausible-looking numbers but ranks a brochureware site above a
structured one is worse than no scoring system, because it looks credible.
"""

from __future__ import annotations

import pytest

from wasl.crawler.detectors import extract_all
from wasl.scoring.cli import load_fixture, neutral_artifacts
from wasl.scoring.rubric import DECLARED_TOTAL, format_report, score_site, scoring_input_from_crawl
from wasl.scoring.types import Confidence


def score_fixture(name: str, **overrides):
    page = load_fixture(name)
    pages = [page]
    store = extract_all(pages, neutral_artifacts(page.final_url))
    scoring_input = scoring_input_from_crawl(store, pages)
    if overrides:
        from dataclasses import replace

        scoring_input = replace(scoring_input, **overrides)
    return score_site(store, scoring_input), store


# --- rubric integrity --------------------------------------------------------


def test_the_declared_rubric_totals_one_hundred() -> None:
    score, _ = score_fixture("rich_site")
    assert sum(axis.max_points for axis in score.axes) == DECLARED_TOTAL


def test_each_axis_matches_its_published_maximum() -> None:
    score, _ = score_fixture("rich_site")
    expected = {1: 15, 2: 20, 3: 25, 4: 15, 5: 15, 6: 10}
    assert {a.number: a.max_points for a in score.axes} == expected


def test_there_are_six_axes_and_twenty_seven_checks() -> None:
    score, _ = score_fixture("rich_site")
    assert len(score.axes) == 6
    assert len(score.all_checks) == 27


def test_no_check_can_exceed_its_own_ceiling() -> None:
    score, _ = score_fixture("rich_site")
    for check in score.all_checks:
        assert 0 <= check.points_awarded <= check.max_points


# --- discrimination ----------------------------------------------------------


def test_the_rubric_discriminates() -> None:
    """A structured site must outscore a hydration-only one, which must outscore
    brochureware. If this ordering ever breaks, the rubric is measuring noise."""
    rich, _ = score_fixture("rich_site")
    spa, _ = score_fixture("spa_site")
    thin, _ = score_fixture("thin_site")

    assert rich.percentage > spa.percentage > thin.percentage


def test_the_structured_site_scores_well_on_structured_data() -> None:
    rich, _ = score_fixture("rich_site")
    axis2 = next(a for a in rich.axes if a.number == 2)
    assert axis2.points == axis2.max_points


def test_the_brochureware_site_scores_nothing_on_structured_data() -> None:
    thin, _ = score_fixture("thin_site")
    axis2 = next(a for a in thin.axes if a.number == 2)
    assert axis2.points == 0


def test_the_spa_fails_extractability_but_not_everything() -> None:
    """Hydration-only sites are invisible to agents, not badly built in general."""
    spa, _ = score_fixture("spa_site")
    axis4 = next(a for a in spa.axes if a.number == 4)
    server_rendered = next(c for c in axis4.checks if c.check_id == "a4_server_rendered")
    assert server_rendered.points_awarded == 0
    assert spa.total > 0


# --- evidence integrity ------------------------------------------------------


def test_every_awarded_check_cites_evidence() -> None:
    """A point awarded with no citation is exactly what the critic exists to stop."""
    for fixture in ("rich_site", "spa_site", "thin_site"):
        score, _ = score_fixture(fixture)
        for check in score.all_checks:
            if check.points_awarded > 0:
                assert check.evidence_refs, (
                    f"{fixture}: {check.check_id} awarded {check.points_awarded} points "
                    "with no evidence reference"
                )


def test_every_citation_resolves_to_real_evidence() -> None:
    """citation_validity == 1.00, at the rubric layer."""
    for fixture in ("rich_site", "spa_site", "thin_site"):
        score, store = score_fixture(fixture)
        dangling = store.verify_references(score.evidence_refs)
        assert dangling == [], f"{fixture}: dangling evidence refs {dangling}"


# --- suppression and the denominator ----------------------------------------


def test_suppressed_checks_shrink_the_denominator() -> None:
    score, _ = score_fixture("thin_site")
    assert score.max_possible < DECLARED_TOTAL
    assert score.max_possible == DECLARED_TOTAL - sum(
        c.max_points for c in score.suppressed_checks
    )


def test_suppressed_checks_never_award_points() -> None:
    for fixture in ("rich_site", "spa_site", "thin_site"):
        score, _ = score_fixture(fixture)
        for check in score.suppressed_checks:
            assert check.points_awarded == 0
            assert check.counted_max == 0


# --- confidence --------------------------------------------------------------


def test_a_single_page_crawl_suppresses_the_band() -> None:
    score, _ = score_fixture("rich_site")
    assert score.confidence is Confidence.LOW
    assert score.band is None


def test_a_healthy_crawl_produces_a_band() -> None:
    score, _ = score_fixture("rich_site", pages_crawled=12, pages_ok=12)
    assert score.confidence is Confidence.HIGH
    assert score.band is not None


def test_the_band_matches_the_percentage() -> None:
    from wasl.scoring.bands import band_for

    score, _ = score_fixture("rich_site", pages_crawled=12, pages_ok=12)
    assert score.band == band_for(score.percentage).value


# --- report ------------------------------------------------------------------


def test_the_report_renders_every_axis_and_check() -> None:
    score, _ = score_fixture("rich_site")
    report = format_report(score, domain="rich_site")

    for axis in score.axes:
        assert axis.name in report
    for check in score.all_checks:
        assert check.label in report


def test_the_report_states_why_the_band_was_suppressed() -> None:
    score, _ = score_fixture("rich_site")
    report = format_report(score)
    assert "SUPPRESSED" in report
    assert "8-page floor" in report


def test_the_report_explains_a_reduced_denominator() -> None:
    score, _ = score_fixture("thin_site")
    report = format_report(score)
    assert "denominator reduced from 100" in report
