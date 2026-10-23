"""align payout provider_name default with actual executing adapter

Revision ID: 004_payout_provider_name_default
Revises: 003_behavioral_twins
Create Date: 2026-10-22 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004_payout_provider_name_default"
down_revision: str | None = "003_behavioral_twins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payout_requests") as batch_op:
        batch_op.alter_column(
            "provider_name",
            existing_type=sa.String(length=32),
            server_default="none",
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("payout_requests") as batch_op:
        batch_op.alter_column(
            "provider_name",
            existing_type=sa.String(length=32),
            server_default="mock",
            existing_nullable=False,
        )
