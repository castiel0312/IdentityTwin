"""agentic commerce registry, delegation grants and audit trail

Revision ID: 005_agentic_commerce
Revises: 004_payout_provider_name_default
Create Date: 2026-10-22 21:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005_agentic_commerce"
down_revision: str | None = "004_payout_provider_name_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_registrations",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("vendor", sa.String(length=128), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("max_payout_amount", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
            ["merchant_id"],
            ["merchants.merchant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("agent_id"),
    )
    op.create_index(
        "ix_agent_registrations_merchant_id", "agent_registrations", ["merchant_id"]
    )
    op.create_index(
        "ix_agent_registrations_merchant_status",
        "agent_registrations",
        ["merchant_id", "status"],
    )

    op.create_table(
        "agent_authorization_grants",
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("max_amount", sa.Float(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delegated_by_user_id", sa.Uuid(), nullable=True),
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
            ["agent_id"], ["agent_registrations.agent_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["delegated_by_user_id"], ["users.user_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("grant_id"),
    )
    op.create_index(
        "ix_agent_authorization_grants_agent_id",
        "agent_authorization_grants",
        ["agent_id"],
    )
    op.create_index(
        "ix_agent_authorization_grants_merchant_id",
        "agent_authorization_grants",
        ["merchant_id"],
    )
    op.create_index(
        "ix_agent_authorization_grants_user_id",
        "agent_authorization_grants",
        ["user_id"],
    )
    op.create_index(
        "ix_agent_authorization_grants_session_id",
        "agent_authorization_grants",
        ["session_id"],
    )
    op.create_index(
        "ix_agent_grants_agent_merchant",
        "agent_authorization_grants",
        ["agent_id", "merchant_id"],
    )
    op.create_index(
        "ix_agent_grants_expiry", "agent_authorization_grants", ["expires_at"]
    )

    op.create_table(
        "agentic_commerce_audit",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=True),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("payout_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=64), nullable=True),
        sa.Column("agent_context", sa.JSON(), nullable=False),
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
            ["agent_id"], ["agent_registrations.agent_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"], ["agent_authorization_grants.grant_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["payout_id"], ["payout_requests.payout_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(
        "ix_agentic_commerce_audit_agent_id", "agentic_commerce_audit", ["agent_id"]
    )
    op.create_index(
        "ix_agentic_commerce_audit_grant_id", "agentic_commerce_audit", ["grant_id"]
    )
    op.create_index(
        "ix_agentic_commerce_audit_merchant_id", "agentic_commerce_audit", ["merchant_id"]
    )
    op.create_index(
        "ix_agentic_commerce_audit_user_id", "agentic_commerce_audit", ["user_id"]
    )
    op.create_index(
        "ix_agentic_commerce_audit_session_id", "agentic_commerce_audit", ["session_id"]
    )
    op.create_index(
        "ix_agentic_commerce_audit_payout_id", "agentic_commerce_audit", ["payout_id"]
    )
    op.create_index(
        "ix_agentic_commerce_audit_idempotency_key",
        "agentic_commerce_audit",
        ["idempotency_key"],
    )
    op.create_index(
        "ix_agentic_audit_merchant_key",
        "agentic_commerce_audit",
        ["merchant_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_agentic_audit_merchant_key", table_name="agentic_commerce_audit")
    op.drop_index("ix_agentic_commerce_audit_idempotency_key", table_name="agentic_commerce_audit")
    op.drop_index("ix_agentic_commerce_audit_payout_id", table_name="agentic_commerce_audit")
    op.drop_index("ix_agentic_commerce_audit_session_id", table_name="agentic_commerce_audit")
    op.drop_index("ix_agentic_commerce_audit_user_id", table_name="agentic_commerce_audit")
    op.drop_index("ix_agentic_commerce_audit_merchant_id", table_name="agentic_commerce_audit")
    op.drop_index("ix_agentic_commerce_audit_grant_id", table_name="agentic_commerce_audit")
    op.drop_index("ix_agentic_commerce_audit_agent_id", table_name="agentic_commerce_audit")
    op.drop_table("agentic_commerce_audit")

    op.drop_index("ix_agent_grants_expiry", table_name="agent_authorization_grants")
    op.drop_index("ix_agent_grants_agent_merchant", table_name="agent_authorization_grants")
    op.drop_index("ix_agent_authorization_grants_session_id", table_name="agent_authorization_grants")
    op.drop_index("ix_agent_authorization_grants_user_id", table_name="agent_authorization_grants")
    op.drop_index("ix_agent_authorization_grants_merchant_id", table_name="agent_authorization_grants")
    op.drop_index("ix_agent_authorization_grants_agent_id", table_name="agent_authorization_grants")
    op.drop_table("agent_authorization_grants")

    op.drop_index("ix_agent_registrations_merchant_status", table_name="agent_registrations")
    op.drop_index("ix_agent_registrations_merchant_id", table_name="agent_registrations")
    op.drop_table("agent_registrations")
