"""Store max_possible alongside the leaderboard total.

A suppressed check leaves the denominator as well as the numerator, so a scan's
maximum is not a constant. The golden run alone produced five different values
(81, 89, 90, 94, 97) depending on which checks could be evaluated.

Ranking on `total` would therefore rank 14/81 level with 14/97. Percentage is
derived at read time rather than stored, so a rubric correction cannot leave a
stale computed column disagreeing with its own inputs.

Revision ID: 0002_leaderboard_max_possible
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_leaderboard_max_possible"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leaderboard_entries",
        sa.Column("max_possible", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leaderboard_entries", "max_possible")
