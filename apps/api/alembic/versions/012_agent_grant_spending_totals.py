"""track cumulative and reserved agent grant spending

Revision ID: 012_agent_grant_spending_totals
Revises: 011_payout_reconciliation
Create Date: 2026-11-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "012_agent_grant_spending_totals"
down_revision: str | None = "011_payout_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_authorization_grants") as batch_op:
        batch_op.add_column(
            sa.Column(
                "total_consumed_amount",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "reserved_amount",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_authorization_grants") as batch_op:
        batch_op.drop_column("reserved_amount")
        batch_op.drop_column("total_consumed_amount")
