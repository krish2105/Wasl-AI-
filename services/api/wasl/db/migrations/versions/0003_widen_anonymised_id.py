"""Widen leaderboard_entries.anonymised_id from 16 to 64 characters.

Caught by `scripts/batch_crawl.py` preflight before a single request was sent.
The published label for a government entity is the entire string — "UAE Federal
Portal (GOV-14)" is 27 characters — and it is what the API returns in place of
the real name.

At VARCHAR(16) the insert would have failed partway through a 100-domain run,
after hours of real requests to third parties. Truncating instead was not an
option: the published identifier would no longer be the one the API contract
specifies, and the anonymisation scheme depends on that identifier being stable
and complete.

Revision ID: 0003_widen_anonymised_id
Revises: 0002_leaderboard_max_possible
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_widen_anonymised_id"
down_revision: str | None = "0002_leaderboard_max_possible"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "leaderboard_entries",
        "anonymised_id",
        existing_type=sa.String(16),
        type_=sa.String(64),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Narrowing truncates. Anything already published under a full label would
    # silently become a different identifier, so refuse rather than corrupt.
    op.execute(
        "DELETE FROM leaderboard_entries WHERE length(anonymised_id) > 16"
    )
    op.alter_column(
        "leaderboard_entries",
        "anonymised_id",
        existing_type=sa.String(64),
        type_=sa.String(16),
        existing_nullable=True,
    )
