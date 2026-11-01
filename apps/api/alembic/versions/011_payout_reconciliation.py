"""add automated payout reconciliation tracking fields

Revision ID: 011_payout_reconciliation
Revises: 010_normalized_honey_workspace
Create Date: 2026-11-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "011_payout_reconciliation"
down_revision: str | None = "010_normalized_honey_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payout_requests") as batch_op:
        batch_op.add_column(
            sa.Column(
                "reconciliation_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("escalation_reason", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reconciliation_claimed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            "ix_payouts_next_retry",
            ["next_retry_at"],
        )
        batch_op.create_index(
            "ix_payouts_reconciliation",
            ["status", "next_retry_at", "escalated_at"],
        )
        batch_op.create_index(
            "ix_payouts_claimed_at",
            ["reconciliation_claimed_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("payout_requests") as batch_op:
        batch_op.drop_index("ix_payouts_reconciliation")
        batch_op.drop_index("ix_payouts_next_retry")
        batch_op.drop_column("escalation_reason")
        batch_op.drop_column("escalated_at")
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("last_reconciled_at")
        batch_op.drop_column("reconciliation_attempts")
