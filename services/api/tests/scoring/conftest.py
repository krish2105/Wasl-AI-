"""Shared builders for rubric tests.

Scoring tests are built from hand-assembled evidence rather than from fixture
HTML wherever possible. The reason is isolation: if a scoring test fails, it
should mean the *check* is wrong, not that a detector two layers away changed
what it emits. The end-to-end path is covered separately in test_rubric.py.
"""

from __future__ import annotations

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.scoring.types import ScoringInput

URL = "https://example.com/page"


def ev(kind: str, selector: str, raw: str = "sample evidence", *, url: str = URL, phase: str = "pre_js") -> Evidence:
    """One piece of evidence, with sensible defaults."""
    return Evidence(source_url=url, kind=kind, selector=selector, raw=raw, phase=phase)  # type: ignore[arg-type]


def store(*evidence: Evidence) -> EvidenceStore:
    return EvidenceStore(evidence)


def scoring_input(
    *,
    pages_crawled: int = 12,
    pages_ok: int = 12,
    pages_robots_blocked: int = 0,
    degraded: bool = False,
    evidence: EvidenceStore | None = None,
) -> ScoringInput:
    return ScoringInput(
        evidence=evidence or EvidenceStore(),
        pages_crawled=pages_crawled,
        pages_ok=pages_ok,
        pages_robots_blocked=pages_robots_blocked,
        degraded=degraded,
    )


def by_id(checks, check_id: str):
    """Pull one check out of an axis result."""
    found = [c for c in checks if c.check_id == check_id]
    assert found, f"{check_id} not found in {[c.check_id for c in checks]}"
    return found[0]
