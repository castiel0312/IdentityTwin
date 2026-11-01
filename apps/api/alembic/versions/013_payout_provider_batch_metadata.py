"""persist provider batch metadata for payouts

Revision ID: 013_payout_batch_meta
Revises: 012_agent_grant_spending_totals
Create Date: 2026-11-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013_payout_batch_meta"
down_revision: str | None = "012_agent_grant_spending_totals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payout_requests") as batch_op:
        batch_op.add_column(sa.Column("provider_batch_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("sender_batch_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("sender_item_id", sa.String(length=128), nullable=True))
        batch_op.create_index("ix_payouts_provider_batch_id", ["provider_batch_id"])


def downgrade() -> None:
    with op.batch_alter_table("payout_requests") as batch_op:
        batch_op.drop_index("ix_payouts_provider_batch_id")
        batch_op.drop_column("sender_item_id")
        batch_op.drop_column("sender_batch_id")
        batch_op.drop_column("provider_batch_id")
