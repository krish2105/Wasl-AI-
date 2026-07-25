"""Score node. Deterministic rubric. No LLM. Ever.

Note what this node does NOT receive: `state.accepted_capabilities` is never read
here. The rubric is a function of evidence alone, which is what makes the score
reproducible without a model and independent of anything the critic decided.
"""

from __future__ import annotations

import logging

from wasl.graph.state import WaslState
from wasl.obs.tracing import node_span
from wasl.scoring.rubric import score_site
from wasl.scoring.types import ScoringInput

logger = logging.getLogger(__name__)


async def score(state: WaslState, store=None) -> dict:
    """Run the rubric over the evidence."""
    with node_span("score", job_id=state.job_id) as span:
        if store is None:
            return {"errors": ["score: no evidence store supplied"]}

        scoring_input = ScoringInput(
            evidence=store,
            pages_crawled=len(state.pages),
            pages_ok=state.pages_ok,
            pages_robots_blocked=state.pages_robots_blocked,
            degraded=state.degraded,
        )

        result = score_site(store, scoring_input)

        span.set_attribute("wasl.score.total", result.total)
        span.set_attribute("wasl.score.max", result.max_possible)
        span.set_attribute("wasl.score.band", result.band or "suppressed")
        span.set_attribute("wasl.score.confidence", result.confidence.value)

        logger.info(
            "score: %d/%d, band=%s, confidence=%s",
            result.total,
            result.max_possible,
            result.band or "SUPPRESSED",
            result.confidence.value,
        )

        return {
            "score": {
                "total": result.total,
                "max_possible": result.max_possible,
                "percentage": round(result.percentage, 1),
                "band": result.band,
                "confidence": result.confidence.value,
                "confidence_reason": result.confidence_reason,
                "degraded": result.degraded,
                "rubric_version": result.rubric_version,
                "axes": [
                    {
                        "number": axis.number,
                        "name": axis.name,
                        "points": axis.points,
                        "max_points": axis.max_points,
                        "counted_max": axis.counted_max,
                        "checks": [
                            {
                                "check_id": c.check_id,
                                "label": c.label,
                                "points_awarded": c.points_awarded,
                                "max_points": c.max_points,
                                "evidence_refs": list(c.evidence_refs),
                                "suppressed": c.suppressed,
                                "suppressed_reason": c.suppressed_reason,
                                "detail": c.detail,
                            }
                            for c in axis.checks
                        ],
                    }
                    for axis in result.axes
                ],
            },
            "_score": result,
        }
