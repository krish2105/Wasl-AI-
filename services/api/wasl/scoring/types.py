"""Result types for the rubric.

The shape worth explaining is `CheckResult.suppressed`.

A check can end in three states, not two. It can pass, it can fail, or it can be
**unevaluable** — we could not gather the evidence needed to judge it either way.
The clearest case is a degraded capture: without a browser there is no post-JS
DOM, so the pre-JS/post-JS ratio is not zero, it is *unknown*.

Scoring an unknown as zero is a quiet lie that makes every degraded scan look
worse than the site deserves. So a suppressed check leaves both the numerator and
the denominator, `max_possible` shrinks, and the report says which checks were
dropped and why. A percentage over a smaller denominator is honest; a zero over
the full one is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Confidence(StrEnum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One rubric check. The atom the Evidence Drawer opens on."""

    check_id: str
    label: str
    points_awarded: int
    max_points: int
    evidence_refs: tuple[str, ...] = ()
    confidence: float = 1.0
    suppressed: bool = False
    suppressed_reason: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.points_awarded > self.max_points:
            raise ValueError(
                f"{self.check_id}: awarded {self.points_awarded} of a maximum "
                f"{self.max_points}. A check cannot exceed its own ceiling."
            )
        if self.points_awarded < 0:
            raise ValueError(f"{self.check_id}: negative points are not a thing.")
        if self.suppressed and self.points_awarded:
            raise ValueError(
                f"{self.check_id}: a suppressed check cannot award points — it was not evaluated."
            )

    @property
    def counted_max(self) -> int:
        """What this check contributes to the denominator. Zero when suppressed."""
        return 0 if self.suppressed else self.max_points

    @property
    def passed(self) -> bool:
        return not self.suppressed and self.points_awarded == self.max_points


@dataclass(frozen=True, slots=True)
class AxisResult:
    """One of the six axes."""

    number: int
    name: str
    checks: tuple[CheckResult, ...]

    @property
    def points(self) -> int:
        return sum(c.points_awarded for c in self.checks)

    @property
    def max_points(self) -> int:
        """Declared ceiling, before suppression. Always the rubric's published number."""
        return sum(c.max_points for c in self.checks)

    @property
    def counted_max(self) -> int:
        return sum(c.counted_max for c in self.checks)

    @property
    def suppressed_checks(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.suppressed)


@dataclass(frozen=True, slots=True)
class WariScore:
    """The whole result.

    `band` is None when confidence is low. That is deliberate: a band is a
    headline claim, and a headline on thin evidence is worse than no headline.
    The number remains visible, with the caveat attached.
    """

    total: int
    max_possible: int
    band: str | None
    confidence: Confidence
    confidence_reason: str | None
    axes: tuple[AxisResult, ...]
    pages_crawled: int
    pages_robots_blocked: int
    degraded: bool = False
    rubric_version: str = "1.0"

    @property
    def percentage(self) -> float:
        return 100.0 * self.total / self.max_possible if self.max_possible else 0.0

    @property
    def all_checks(self) -> tuple[CheckResult, ...]:
        return tuple(check for axis in self.axes for check in axis.checks)

    @property
    def suppressed_checks(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.all_checks if c.suppressed)

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for check in self.all_checks:
            for ref in check.evidence_refs:
                seen.setdefault(ref, None)
        return tuple(seen)


@dataclass(frozen=True, slots=True)
class ScoringInput:
    """Everything the rubric is allowed to look at.

    Note what is absent: candidate capabilities, tool schemas, model output of
    any kind. The rubric cannot read them because they are not in this object,
    which makes the deterministic-scoring rule structural rather than a
    convention someone has to remember.
    """

    evidence: object  # EvidenceStore; typed loosely to keep this module import-light
    pages_crawled: int
    pages_ok: int
    pages_robots_blocked: int
    degraded: bool = False
    pages_with_canonical: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def robots_blocked_ratio(self) -> float:
        return self.pages_robots_blocked / self.pages_crawled if self.pages_crawled else 0.0
