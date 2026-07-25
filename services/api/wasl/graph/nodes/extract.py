"""Extract node. Deterministic. No model.

Runs all seventeen detectors over the crawl and flattens the result into
serialisable evidence records. Also lifts injection findings into state, because
they are both a scoring input and a user-facing security finding.
"""

from __future__ import annotations

import logging

from wasl.crawler.detectors import extract_all
from wasl.graph.state import EvidenceRecord, Finding, WaslState
from wasl.obs.tracing import node_span

logger = logging.getLogger(__name__)


def to_records(store) -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            id=e.id,
            source_url=e.source_url,
            kind=e.kind,
            selector=e.selector,
            raw=e.raw,
            phase=e.phase,
        )
        for e in store
    ]


def injection_findings(store) -> list[Finding]:
    """Injection evidence, lifted into state as findings.

    Note the polarity: an injection row is evidence *against* the site on Axis 6.
    The `injection#clean` rows are not findings — they are the receipt that a
    scan happened, and they stay in evidence only.
    """
    findings: list[Finding] = []
    for evidence in store.by_kind("injection"):
        if (evidence.selector or "") == "injection#clean":
            continue
        category = next(
            (
                line.split(": ", 1)[1]
                for line in evidence.raw.splitlines()
                if line.startswith("category: ")
            ),
            "unknown",
        )
        severity = next(
            (
                line.split("severity ", 1)[1].rstrip(")")
                for line in evidence.raw.splitlines()
                if "severity " in line
            ),
            "medium",
        )
        findings.append(
            Finding(
                kind="injection",
                category=category,
                severity=severity if severity in {"info", "low", "medium", "high"} else "medium",
                description=evidence.raw.splitlines()[-1][:400],
                evidence_ids=[evidence.id],
            )
        )
    return findings


async def extract(state: WaslState, pages=None, artifacts=None) -> dict:
    """Run every detector. Pure functions only — no network, no model."""
    with node_span("extract", job_id=state.job_id):
        if pages is None or artifacts is None:
            return {"errors": ["extract: no captured pages were supplied by the crawl node"]}

        store = extract_all(pages, artifacts)
        records = to_records(store)
        findings = injection_findings(store)

        logger.info(
            "extract complete: %d evidence rows across %d kinds, %d injection finding(s)",
            len(records),
            len({r.kind for r in records}),
            len(findings),
        )

        return {
            "evidence": records,
            "security_findings": findings,
            "_store": store,
        }
