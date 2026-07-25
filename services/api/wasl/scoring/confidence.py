"""Confidence suppression.

The rule from the spec: fewer than 8 pages successfully crawled, or more than 30%
robots-blocked, and the report shows LOW CONFIDENCE with the grade band
suppressed.

Why suppress the band rather than lower the score: those are different claims. A
thin crawl does not mean the site is bad, it means we do not know. Publishing
"Invisible" for a site we only managed to read two pages of would be an assertion
the evidence does not support, and on a public leaderboard naming real companies
that is the kind of error that matters.

The number still shows. The headline does not.
"""

from __future__ import annotations

from dataclasses import dataclass

from wasl.scoring.types import Confidence, ScoringInput

MIN_PAGES_FOR_CONFIDENCE = 8
MAX_ROBOTS_BLOCKED_RATIO = 0.30


@dataclass(frozen=True, slots=True)
class ConfidenceVerdict:
    level: Confidence
    reason: str | None

    @property
    def suppress_band(self) -> bool:
        return self.level is Confidence.LOW


def assess(scoring_input: ScoringInput) -> ConfidenceVerdict:
    """Decide whether this crawl supports a confident headline."""
    reasons: list[str] = []

    if scoring_input.pages_ok < MIN_PAGES_FOR_CONFIDENCE:
        reasons.append(
            f"only {scoring_input.pages_ok} page(s) were successfully crawled, "
            f"below the {MIN_PAGES_FOR_CONFIDENCE}-page floor"
        )

    ratio = scoring_input.robots_blocked_ratio
    if ratio > MAX_ROBOTS_BLOCKED_RATIO:
        reasons.append(
            f"{ratio:.0%} of pages were robots-blocked, above the "
            f"{MAX_ROBOTS_BLOCKED_RATIO:.0%} threshold"
        )

    if reasons:
        return ConfidenceVerdict(
            Confidence.LOW,
            "Grade band suppressed: " + "; and ".join(reasons) + ".",
        )

    # Degraded capture does not by itself suppress the band — the affected checks
    # are already suppressed individually, so the denominator has adjusted and
    # the remaining evidence is as sound as any other crawl's.
    if scoring_input.degraded:
        return ConfidenceVerdict(
            Confidence.HIGH,
            "Captured without a browser; rendering-dependent checks were suppressed "
            "and excluded from the total.",
        )

    return ConfidenceVerdict(Confidence.HIGH, None)
