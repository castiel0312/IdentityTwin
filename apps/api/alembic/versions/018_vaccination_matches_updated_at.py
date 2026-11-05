"""add updated_at to vaccination_matches

Revision ID: 018_match_updated_at
Revises: 017_vaccination_signatures
Create Date: 2026-11-04 00:00:00.000000

The vaccination_matches table was created by 017 without an updated_at column,
which the TimestampMixin on the VaccinationMatch model expects. This migration
adds the missing column so existing databases (already at 017) stay consistent
with the model, while fresh databases get it directly from 017.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "018_match_updated_at"
down_revision: str | None = "017_vaccination_signatures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vaccination_matches",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("vaccination_matches", "updated_at")
