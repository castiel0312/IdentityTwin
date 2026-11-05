"""persist tenant-scoped domain events for authenticated replay

Revision ID: 019_durable_domain_events
Revises: 018_match_updated_at
Create Date: 2026-11-04 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "019_durable_domain_events"
down_revision: str | None = "018_match_updated_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "domain_event_cursors",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("last_event_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("merchant_id"),
    )
    op.create_table(
        "domain_events",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("merchant_id", "event_id"),
    )
    op.create_index(
        "ix_domain_events_merchant_created",
        "domain_events",
        ["merchant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_domain_events_merchant_created", table_name="domain_events")
    op.drop_table("domain_events")
    op.drop_table("domain_event_cursors")
