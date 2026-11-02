"""persist read-only advisory AI investigation bundles

Revision ID: 014_investigations
Revises: 013_payout_batch_meta
Create Date: 2026-11-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "014_investigations"
down_revision: str | None = "013_payout_batch_meta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("ai_used", sa.Boolean(), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("bundle", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.incident_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("investigation_id"),
    )
    op.create_index("ix_investigations_merchant_id", "investigations", ["merchant_id"])
    op.create_index("ix_investigations_incident_id", "investigations", ["incident_id"])
    op.create_index("ix_investigations_session_id", "investigations", ["session_id"])
    op.create_index(
        "ix_investigations_merchant_created",
        "investigations",
        ["merchant_id", "created_at"],
    )
    op.create_index(
        "ix_investigations_incident_created",
        "investigations",
        ["incident_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_investigations_incident_created", table_name="investigations")
    op.drop_index("ix_investigations_merchant_created", table_name="investigations")
    op.drop_index("ix_investigations_session_id", table_name="investigations")
    op.drop_index("ix_investigations_incident_id", table_name="investigations")
    op.drop_index("ix_investigations_merchant_id", table_name="investigations")
    op.drop_table("investigations")
