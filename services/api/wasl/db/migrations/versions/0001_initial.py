"""Initial schema: jobs, evidence spine, scores, artifacts, leaderboard.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    # Idempotent so this migration works against a fresh Neon database as well as
    # the local compose stack, where the init script has already created it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("root_url", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("budget", sa.String(16), nullable=False, server_default="interactive"),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("degraded_reason", sa.Text()),
        sa.Column("submitted_by_user", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_jobs_domain", "jobs", ["domain"])

    op.create_table(
        "pages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text()),
        sa.Column("status_code", sa.Integer()),
        sa.Column("headers", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("response_time_ms", sa.Integer()),
        sa.Column("robots_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fetch_error", sa.Text()),
        sa.Column("pre_js_path", sa.Text()),
        sa.Column("post_js_path", sa.Text()),
        sa.Column("pre_js_text_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("post_js_text_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("job_id", "url", name="uq_pages_job_url"),
    )
    op.create_index("ix_pages_job_id", "pages", ["job_id"])

    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_id", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("selector", sa.Text()),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("phase", sa.String(8), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("job_id", "evidence_id", name="uq_evidence_job_eid"),
    )
    op.create_index("ix_evidence_job_id", "evidence", ["job_id"])
    op.create_index("ix_evidence_job_kind", "evidence", ["job_id", "kind"])

    op.create_table(
        "capabilities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("verb", sa.String(32), nullable=False),
        sa.Column("noun", sa.String(64), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(), nullable=False),
        sa.Column("tool_schema", postgresql.JSONB()),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state_changing", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("emitted_as_tool", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_capabilities_job_id", "capabilities", ["job_id"])

    op.create_table(
        "rejections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_name", sa.String(128), nullable=False),
        sa.Column("rule_id", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("critic_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_rejections_job_id", "rejections", ["job_id"])

    op.create_table(
        "scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("max_possible", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("band", sa.String(16)),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("confidence_reason", sa.Text()),
        sa.Column("pages_crawled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_robots_blocked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rubric_version", sa.String(16), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "axis_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("score_id", sa.Integer(), sa.ForeignKey("scores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("axis_number", sa.Integer(), nullable=False),
        sa.Column("axis_name", sa.String(48), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("max_points", sa.Integer(), nullable=False),
        sa.UniqueConstraint("score_id", "axis_number", name="uq_axis_score_number"),
    )
    op.create_index("ix_axis_scores_score_id", "axis_scores", ["score_id"])

    op.create_table(
        "check_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("axis_score_id", sa.Integer(), sa.ForeignKey("axis_scores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("check_id", sa.String(48), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("points_awarded", sa.Integer(), nullable=False),
        sa.Column("max_points", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("suppressed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suppressed_reason", sa.Text()),
    )
    op.create_index("ix_check_results_axis_score_id", "check_results", ["axis_score_id"])

    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("category", sa.String(48)),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_findings_job_id", "findings", ["job_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_output", sa.Text()),
        sa.Column("tool_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_artifacts_job_id", "artifacts", ["job_id"])

    op.create_table(
        "leaderboard_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("domain", sa.String(253), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("anonymised_id", sa.String(16)),
        sa.Column("is_anonymised", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("group_key", sa.String(48), nullable=False),
        sa.Column("sector_label", sa.String(64), nullable=False),
        sa.Column("is_golden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("total", sa.Integer()),
        sa.Column("band", sa.String(16)),
        sa.Column("confidence", sa.String(8)),
        sa.Column("crawled_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_leaderboard_entries_group_key", "leaderboard_entries", ["group_key"])
    op.create_index("ix_leaderboard_total", "leaderboard_entries", ["total"])


def downgrade() -> None:
    op.drop_table("leaderboard_entries")
    op.drop_table("artifacts")
    op.drop_table("findings")
    op.drop_table("check_results")
    op.drop_table("axis_scores")
    op.drop_table("scores")
    op.drop_table("rejections")
    op.drop_table("capabilities")
    op.drop_table("evidence")
    op.drop_table("pages")
    op.drop_table("jobs")
    # The vector extension is left in place. Another database on the same
    # instance may be using it, and dropping it is not this migration's business.
