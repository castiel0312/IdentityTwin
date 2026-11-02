"""persist advisory Intent Profiler snapshots

Revision ID: 016_intent_profiles
Revises: 015_evidence_scope_columns
Create Date: 2026-11-02 00:20:00.000000

Profiles are immutable, merchant-scoped read models. They do not participate in
risk scoring or enforcement and contain only derived, bounded evidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "016_intent_profiles"
down_revision: str | None = "015_evidence_scope_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intent_profiles",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("profile_id"),
    )
    op.create_index("ix_intent_profiles_merchant_id", "intent_profiles", ["merchant_id"])
    op.create_index("ix_intent_profiles_session_id", "intent_profiles", ["session_id"])
    op.create_index(
        "ix_intent_profiles_merchant_created",
        "intent_profiles",
        ["merchant_id", "created_at"],
    )
    op.create_index(
        "ix_intent_profiles_session_created",
        "intent_profiles",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_intent_profiles_session_created", table_name="intent_profiles")
    op.drop_index("ix_intent_profiles_merchant_created", table_name="intent_profiles")
    op.drop_index("ix_intent_profiles_session_id", table_name="intent_profiles")
    op.drop_index("ix_intent_profiles_merchant_id", table_name="intent_profiles")
    op.drop_table("intent_profiles")
