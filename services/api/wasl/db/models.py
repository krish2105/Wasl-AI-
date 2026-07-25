"""Database schema for scans, evidence, scores and generated artifacts.

Why the shape is what it is:

**Evidence is the spine.** Everything downstream — capabilities, sub-scores,
findings — references evidence by ID, and those references are checked. The
`citation_validity` metric is a hard gate at 1.00, which means a dangling
reference is a build failure, not a cosmetic bug. `evidence.evidence_id` is
content-addressed (`sha256(source_url|kind|selector|raw)[:16]`), so the same
snippet found twice within a scan collapses to one row for free.

**Check results are stored individually, not just axis totals.** The UI has to
open an Evidence Drawer on any sub-score and show the exact URL and DOM snippet
that produced it. That is only possible if each of the 26 checks persists its own
points, its own evidence refs, and — when a scan was degraded — the reason it was
suppressed rather than scored zero.

**Rejections are first-class rows.** What the critic refused to generate is
displayed in the UI alongside what it accepted. Storing rejections as durable
records rather than log lines is what makes that panel possible.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Gemini's text-embedding-004 output width. Pinned here rather than inferred so a
# provider change is a deliberate migration, not a silent dimension mismatch.
EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    """Declarative base for all Wasl tables."""


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Job(Base):
    """One scan of one domain.

    `degraded` marks a scan that ran without Playwright — the httpx-only path
    used where headless Chromium cannot run. Such a scan cannot measure the
    pre-JS/post-JS delta, so Axis 4's rendering check is suppressed and the
    denominator shrinks. It is never scored zero, because "we could not look" and
    "we looked and found nothing" are different claims.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    root_url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(253), nullable=False, index=True)

    # queued | crawling | extracting | inducing | critiquing | scoring
    # | awaiting_confirmation | generating | probing | demoing | complete | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    budget: Mapped[str] = mapped_column(String(16), nullable=False, default="interactive")

    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    degraded_reason: Mapped[str | None] = mapped_column(Text)

    submitted_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pages: Mapped[list[Page]] = relationship(back_populates="job", cascade="all, delete-orphan")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    capabilities: Mapped[list[Capability]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    rejections: Mapped[list[Rejection]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    findings: Mapped[list[Finding]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    score: Mapped[Score | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class Page(Base):
    """One fetched URL, captured twice: before and after JavaScript.

    The ratio between `pre_js_text_chars` and `post_js_text_chars` is Axis 4's
    headline signal — it is the difference between a site an agent can read and
    one that only exists after hydration.

    `robots_blocked` records a refusal we honoured. It is evidence about how the
    site treats agents, not a failure of the crawl.
    """

    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    headers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)

    robots_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fetch_error: Mapped[str | None] = mapped_column(Text)

    # Bodies live on disk under data/cache/, not in postgres. We store third-party
    # page content as internal evidence and do not republish it; keeping it out of
    # the database keeps that boundary obvious.
    pre_js_path: Mapped[str | None] = mapped_column(Text)
    post_js_path: Mapped[str | None] = mapped_column(Text)
    pre_js_text_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    post_js_text_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    fetched_at: Mapped[datetime] = _now()

    job: Mapped[Job] = relationship(back_populates="pages")

    __table_args__ = (UniqueConstraint("job_id", "url", name="uq_pages_job_url"),)


class Evidence(Base):
    """A verbatim snippet, with provenance, that some claim rests on.

    `evidence_id` is content-addressed and unique per job. `raw` is the actual
    text, truncated but never paraphrased — if we cannot show a user the exact
    string a score came from, we do not have evidence.
    """

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    evidence_id: Mapped[str] = mapped_column(String(16), nullable=False)

    # jsonld | meta | dom | header | robots | openapi | form | link | text
    # | sitemap | llmstxt | wellknown | injection
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    selector: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(String(8), nullable=False)  # pre_js | post_js

    # Populated only when a site produces more evidence than the induce node's
    # context budget allows. Below that threshold we pass everything and skip
    # retrieval entirely — a corpus that fits in context does not need a pipeline.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    captured_at: Mapped[datetime] = _now()

    job: Mapped[Job] = relationship(back_populates="evidence")

    __table_args__ = (
        UniqueConstraint("job_id", "evidence_id", name="uq_evidence_job_eid"),
        Index("ix_evidence_job_kind", "job_id", "kind"),
    )


class Capability(Base):
    """Something the site can do, as proposed by the induce node.

    `evidence_ids` is never empty — the Pydantic model that produces these rows
    rejects an empty list at construction, so an uncited capability cannot reach
    the database.

    `state_changing` capabilities are recorded because detecting them is useful,
    and are never emitted as tools. Generating a "book the room" tool for a site
    we do not control is how a portfolio project becomes an incident.
    """

    __tablename__ = "capabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    verb: Mapped[str] = mapped_column(String(32), nullable=False)
    noun: Mapped[str] = mapped_column(String(64), nullable=False)

    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    tool_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state_changing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    emitted_as_tool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = _now()

    job: Mapped[Job] = relationship(back_populates="capabilities")


class Rejection(Base):
    """A capability the critic refused, and why.

    Surfaced in the UI. A system that shows what it declined to generate is more
    credible than one that shows only its successes, and this is the cheapest
    credibility available.
    """

    __tablename__ = "rejections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    capability_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # One of the five enumerated criteria: no_evidence | evidence_mismatch
    # | unbounded_param | state_changing | injection_detected
    rule_id: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    critic_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = _now()

    job: Mapped[Job] = relationship(back_populates="rejections")


class Score(Base):
    """The WARI result for a job. Produced by pure functions over evidence.

    `max_possible` is normally 100 but shrinks on a degraded scan, where checks
    that could not be evaluated are suppressed rather than failed.

    `band` is null when `confidence` is low — fewer than 8 pages reached, or more
    than 30% robots-blocked. A confident-looking band on thin evidence is worse
    than no band at all.
    """

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    total: Mapped[int] = mapped_column(Integer, nullable=False)
    max_possible: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    band: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)  # high | low
    confidence_reason: Mapped[str | None] = mapped_column(Text)

    pages_crawled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_robots_blocked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    rubric_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    created_at: Mapped[datetime] = _now()

    job: Mapped[Job] = relationship(back_populates="score")
    axes: Mapped[list[AxisScore]] = relationship(
        back_populates="score", cascade="all, delete-orphan"
    )


class AxisScore(Base):
    """One of the six axes."""

    __tablename__ = "axis_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    score_id: Mapped[int] = mapped_column(
        ForeignKey("scores.id", ondelete="CASCADE"), nullable=False, index=True
    )

    axis_number: Mapped[int] = mapped_column(Integer, nullable=False)
    axis_name: Mapped[str] = mapped_column(String(48), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    max_points: Mapped[int] = mapped_column(Integer, nullable=False)

    score: Mapped[Score] = relationship(back_populates="axes")
    checks: Mapped[list[CheckResult]] = relationship(
        back_populates="axis", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("score_id", "axis_number", name="uq_axis_score_number"),)


class CheckResult(Base):
    """One of the 26 individual rubric checks.

    Stored individually so the Evidence Drawer can open on any sub-score and show
    the exact snippets behind it. `evidence_refs` holds evidence IDs; every one
    must resolve.
    """

    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    axis_score_id: Mapped[int] = mapped_column(
        ForeignKey("axis_scores.id", ondelete="CASCADE"), nullable=False, index=True
    )

    check_id: Mapped[str] = mapped_column(String(48), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=False)
    max_points: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # A suppressed check is excluded from both numerator and denominator. Used
    # when a degraded scan could not evaluate it at all.
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suppressed_reason: Mapped[str | None] = mapped_column(Text)

    axis: Mapped[AxisScore] = relationship(back_populates="checks")


class Finding(Base):
    """A security observation: an injection attempt, or a tool-boundary concern.

    Injection findings feed Axis 6 and the `injection_detection_recall` metric.
    Counting what we catch is what turns a defence into a measurement.
    """

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # injection | tool_boundary
    category: Mapped[str | None] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = _now()

    job: Mapped[Job] = relationship(back_populates="findings")


class Artifact(Base):
    """A generated file offered for download.

    `verified` is set only after the generated server has been imported in a
    clean subprocess and its tools introspected. If it does not import, it does
    not ship.
    """

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # mcp_server|agent_card|llms_txt|zip
    path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_output: Mapped[str | None] = mapped_column(Text)
    tool_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = _now()

    job: Mapped[Job] = relationship(back_populates="artifacts")


class LeaderboardEntry(Base):
    """A published row on the public leaderboard.

    Government and public-sector entities are published under `anonymised_id`
    with `display_name` withheld. Scoring a named ministry as "Invisible" on a
    public page is a different risk category from scoring a commercial vendor,
    and the policy story survives on sector aggregates.
    """

    __tablename__ = "leaderboard_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    domain: Mapped[str] = mapped_column(String(253), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 64, not 16. The published label is the whole string — "UAE Federal Portal
    # (GOV-14)" is 27 characters — and it is what the API contract returns in
    # place of the real name. Truncating it would publish a different identifier
    # than the one the contract specifies, so the column has to hold all of it.
    anonymised_id: Mapped[str | None] = mapped_column(String(64))
    is_anonymised: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    group_key: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    sector_label: Mapped[str] = mapped_column(String(64), nullable=False)
    is_golden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    total: Mapped[int | None] = mapped_column(Integer)
    # Stored alongside the total because it varies. A suppressed check leaves the
    # denominator as well as the numerator, so the golden run alone produced five
    # different maxima (81, 89, 90, 94, 97). Ranking on `total` would put 14/81
    # level with 14/97, which is not a ranking, it is an artefact.
    max_possible: Mapped[int | None] = mapped_column(Integer)
    band: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[str | None] = mapped_column(String(8))

    crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ix_leaderboard_total", "total"),)
