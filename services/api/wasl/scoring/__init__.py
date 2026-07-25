"""The WARI rubric: a deterministic function from evidence to a score.

**This package imports nothing from `wasl.llm`, and it never will.**

That is the load-bearing architectural claim of the whole project, so it is
enforced by a test (`tests/scoring/test_score_is_llm_independent.py`) rather than
left to discipline. Run a full scan with the model nodes disabled and the score
is byte-identical, because no check reads anything a model produced.

Everything here is a pure function over `Evidence`. Same evidence in, same score
out, on every machine, forever. That is what makes a published score auditable
rather than an opinion.
"""

from wasl.scoring.bands import Band, band_for
from wasl.scoring.rubric import score_site
from wasl.scoring.types import AxisResult, CheckResult, Confidence, ScoringInput, WariScore

__all__ = [
    "AxisResult",
    "Band",
    "CheckResult",
    "Confidence",
    "ScoringInput",
    "WariScore",
    "band_for",
    "score_site",
]
