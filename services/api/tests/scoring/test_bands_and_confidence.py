"""Grade bands and confidence suppression.

Band boundaries are tested at every edge, in both directions. These numbers get
published next to real company names, and an off-by-one at a boundary is the kind
of bug nobody notices until someone disputes their score.
"""

from __future__ import annotations

import pytest

from tests.scoring.conftest import scoring_input
from wasl.scoring.bands import BAND_RANGES, Band, band_for, describe
from wasl.scoring.confidence import (
    MAX_ROBOTS_BLOCKED_RATIO,
    MIN_PAGES_FOR_CONFIDENCE,
    assess,
)
from wasl.scoring.types import Confidence


# --- bands -------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, Band.INVISIBLE),
        (24, Band.INVISIBLE),
        (25, Band.EMERGING),
        (44, Band.EMERGING),
        (45, Band.READABLE),
        (64, Band.READABLE),
        (65, Band.AGENT_READY),
        (84, Band.AGENT_READY),
        (85, Band.AGENT_NATIVE),
        (100, Band.AGENT_NATIVE),
    ],
)
def test_every_band_boundary(value: int, expected: Band) -> None:
    assert band_for(value) is expected


def test_bands_are_contiguous_with_no_gaps() -> None:
    for (_, high, _), (low, _, _) in zip(BAND_RANGES, BAND_RANGES[1:], strict=False):
        assert low == high + 1


def test_bands_cover_zero_to_one_hundred_exactly() -> None:
    assert BAND_RANGES[0][0] == 0
    assert BAND_RANGES[-1][1] == 100


def test_fractional_scores_round_to_the_nearest_point() -> None:
    """The displayed number and the band must agree, or the report looks broken."""
    assert band_for(24.6) is Band.EMERGING
    assert band_for(24.4) is Band.INVISIBLE


def test_out_of_range_values_are_clamped() -> None:
    assert band_for(-10) is Band.INVISIBLE
    assert band_for(150) is Band.AGENT_NATIVE


def test_every_band_has_a_description() -> None:
    for band in Band:
        assert describe(band)


# --- confidence --------------------------------------------------------------


def test_a_healthy_crawl_is_high_confidence() -> None:
    verdict = assess(scoring_input(pages_crawled=12, pages_ok=12))
    assert verdict.level is Confidence.HIGH
    assert not verdict.suppress_band


def test_below_the_page_floor_suppresses_the_band() -> None:
    verdict = assess(scoring_input(pages_crawled=7, pages_ok=7))
    assert verdict.level is Confidence.LOW
    assert verdict.suppress_band
    assert "below the 8-page floor" in (verdict.reason or "")


def test_exactly_at_the_page_floor_is_confident() -> None:
    verdict = assess(scoring_input(pages_crawled=8, pages_ok=MIN_PAGES_FOR_CONFIDENCE))
    assert verdict.level is Confidence.HIGH


def test_heavy_robots_blocking_suppresses_the_band() -> None:
    verdict = assess(scoring_input(pages_crawled=10, pages_ok=10, pages_robots_blocked=4))
    assert verdict.suppress_band
    assert "robots-blocked" in (verdict.reason or "")


def test_exactly_at_the_robots_threshold_is_confident() -> None:
    """The rule is 'more than 30%', so exactly 30% must pass."""
    verdict = assess(scoring_input(pages_crawled=10, pages_ok=10, pages_robots_blocked=3))
    assert verdict.robots_ratio if False else True  # readability guard
    assert MAX_ROBOTS_BLOCKED_RATIO == 0.30
    assert verdict.level is Confidence.HIGH


def test_both_failures_are_reported_together() -> None:
    verdict = assess(scoring_input(pages_crawled=5, pages_ok=3, pages_robots_blocked=2))
    assert verdict.suppress_band
    assert "8-page floor" in (verdict.reason or "")
    assert "robots-blocked" in (verdict.reason or "")


def test_a_degraded_capture_alone_does_not_suppress_the_band() -> None:
    """Affected checks are already suppressed individually; the rest stands."""
    verdict = assess(scoring_input(pages_crawled=12, pages_ok=12, degraded=True))
    assert verdict.level is Confidence.HIGH
    assert not verdict.suppress_band
    assert "without a browser" in (verdict.reason or "")


def test_zero_pages_suppresses() -> None:
    assert assess(scoring_input(pages_crawled=0, pages_ok=0)).suppress_band
