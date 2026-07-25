"""The rubric: evidence in, WARI score out. Deterministic, no model, no I/O.

This module is the answer to "how do you know the score means anything?" It is a
pure function. The same evidence produces the same score on every machine, every
time, and every point awarded carries the IDs of the evidence that justified it.

The one subtlety is the denominator. `max_possible` is normally 100, but shrinks
when checks are suppressed — cases where we could not gather the evidence to
judge either way rather than cases where the site failed. A percentage over the
smaller denominator is an honest statement about what we actually measured; a
zero over the full one would be a claim we cannot support.
"""

from __future__ import annotations

from wasl.crawler.evidence import EvidenceStore
from wasl.scoring.axes import AXES
from wasl.scoring.bands import band_for
from wasl.scoring.confidence import assess
from wasl.scoring.types import AxisResult, Confidence, ScoringInput, WariScore

RUBRIC_VERSION = "1.0"
DECLARED_TOTAL = 100


def score_site(store: EvidenceStore, scoring_input: ScoringInput) -> WariScore:
    """Run all six axes over the evidence and assemble the result."""
    axes: list[AxisResult] = []

    for number, name, evaluate, declared_max in AXES:
        checks = evaluate(store, scoring_input)
        axis = AxisResult(number=number, name=name, checks=checks)

        # The published rubric is a contract. If an axis stops summing to its
        # stated maximum, a check was edited without updating the spec, and every
        # score produced since is wrong in a way nobody would notice.
        if axis.max_points != declared_max:
            raise AssertionError(
                f"Axis {number} ({name}) declares {declared_max} points but its checks "
                f"sum to {axis.max_points}. The rubric and the implementation have diverged."
            )
        axes.append(axis)

    total = sum(axis.points for axis in axes)
    max_possible = sum(axis.counted_max for axis in axes)

    declared = sum(axis.max_points for axis in axes)
    if declared != DECLARED_TOTAL:
        raise AssertionError(
            f"The rubric declares {DECLARED_TOTAL} points but the axes sum to {declared}."
        )

    verdict = assess(scoring_input)
    percentage = 100.0 * total / max_possible if max_possible else 0.0

    return WariScore(
        total=total,
        max_possible=max_possible,
        band=None if verdict.suppress_band else band_for(percentage).value,
        confidence=verdict.level,
        confidence_reason=verdict.reason,
        axes=tuple(axes),
        pages_crawled=scoring_input.pages_crawled,
        pages_robots_blocked=scoring_input.pages_robots_blocked,
        degraded=scoring_input.degraded,
        rubric_version=RUBRIC_VERSION,
    )


def scoring_input_from_crawl(store: EvidenceStore, pages) -> ScoringInput:
    """Build a ScoringInput from crawl output.

    Note what is not threaded through: capabilities, tool schemas, model output.
    The rubric is not given them, so it cannot use them even by accident.
    """
    from wasl.crawler.types import CaptureMode

    page_list = list(pages)
    ok = [p for p in page_list if p.ok]

    return ScoringInput(
        evidence=store,
        pages_crawled=len(page_list),
        pages_ok=len(ok),
        pages_robots_blocked=sum(1 for p in page_list if p.robots_blocked),
        degraded=bool(ok) and all(p.mode is CaptureMode.DEGRADED for p in ok),
        pages_with_canonical=len(
            {e.source_url for e in store.by_kind("link") if e.selector == "link[rel=canonical]"}
        ),
    )


def format_report(score: WariScore, *, domain: str = "") -> str:
    """The six-axis table printed at the phase gate."""
    rule = "=" * 78
    lines = [
        rule,
        f"WARI SCORE{f'  —  {domain}' if domain else ''}",
        rule,
        f"  {score.total} / {score.max_possible}"
        + (f"  ({score.percentage:.0f}%)" if score.max_possible != 100 else ""),
        f"  band: {score.band or 'SUPPRESSED — LOW CONFIDENCE'}",
        f"  confidence: {score.confidence.value.upper()}",
    ]
    if score.confidence_reason:
        lines.append(f"  {score.confidence_reason}")
    if score.max_possible != 100:
        lines.append(
            f"  denominator reduced from 100 to {score.max_possible}: "
            f"{len(score.suppressed_checks)} check(s) could not be evaluated"
        )
    lines.append(
        f"  pages: {score.pages_crawled} crawled, {score.pages_robots_blocked} robots-blocked"
        + ("  [DEGRADED CAPTURE]" if score.degraded else "")
    )
    lines.append("")

    for axis in score.axes:
        header = f"  Axis {axis.number} — {axis.name}"
        lines.append(f"{header:<58} {axis.points:>3} / {axis.max_points}")
        for check in axis.checks:
            if check.suppressed:
                marker, value = "~", "  --"
            elif check.passed:
                marker, value = "+", f"{check.points_awarded:>2}/{check.max_points}"
            elif check.points_awarded:
                marker, value = "±", f"{check.points_awarded:>2}/{check.max_points}"
            else:
                marker, value = "-", f"{check.points_awarded:>2}/{check.max_points}"
            lines.append(f"    {marker} {check.label:<62} {value}")
            note = check.suppressed_reason if check.suppressed else check.detail
            if note:
                lines.append(f"        {note[:110]}")
            if check.evidence_refs:
                lines.append(
                    f"        evidence: {', '.join(check.evidence_refs[:4])}"
                    + (f" (+{len(check.evidence_refs) - 4} more)" if len(check.evidence_refs) > 4 else "")
                )
        lines.append("")

    lines.append(f"  key: + full  ± partial  - none  ~ suppressed (not counted)")
    lines.append(f"  rubric v{score.rubric_version} · every award above resolves to stored evidence")
    lines.append("")
    return "\n".join(lines)
