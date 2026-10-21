"""initial schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-10-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. merchants
    op.create_table(
        "merchants",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("merchant_id"),
    )
    op.create_index("ix_merchants_slug", "merchants", ["slug"], unique=True)

    # 2. users
    op.create_table(
        "users",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="merchant"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_merchant_id", "users", ["merchant_id"])

    # 3. sessions
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("trust_level", sa.String(length=32), nullable=False, server_default="NORMAL"),
        sa.Column("risk_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("device_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("ix_sessions_merchant_user", "sessions", ["merchant_id", "user_id"])
    op.create_index("ix_sessions_trust_level", "sessions", ["trust_level"])

    # 4. security_events
    op.create_table(
        "security_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("processed_by_risk_engine", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_security_events_occurred", "security_events", ["occurred_at"])
    op.create_index("ix_security_events_merchant_type", "security_events", ["merchant_id", "event_type"])
    op.create_index("ix_security_events_idempotency_key", "security_events", ["idempotency_key"])

    # 5. risk_decisions
    op.create_table(
        "risk_decisions",
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("trust_level", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("routing_destination", sa.String(length=32), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("risk_signals", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("decision_id"),
    )
    op.create_index("ix_risk_decisions_merchant_eval", "risk_decisions", ["merchant_id", "evaluated_at"])

    # 6. payout_requests
    op.create_table(
        "payout_requests",
        sa.Column("payout_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("reference_note", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_name", sa.String(length=32), nullable=False, server_default="mock"),
        sa.Column("provider_reference", sa.String(length=128), nullable=True),
        sa.Column("provider_payload", sa.JSON(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["risk_decisions.decision_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("payout_id"),
        sa.UniqueConstraint("decision_id"),
    )
    op.create_index("ix_payouts_merchant_idempotency", "payout_requests", ["merchant_id", "idempotency_key"])
    op.create_index("ix_payouts_status", "payout_requests", ["status"])

    # 7. incidents
    op.create_table(
        "incidents",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False, server_default="HIGH"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OPEN"),
        sa.Column("risk_score", sa.Float(), nullable=False, server_default="75.0"),
        sa.Column("trigger_reason", sa.String(length=255), nullable=False),
        sa.Column("evidence_summary", sa.JSON(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("incident_id"),
    )
    op.create_index("ix_incidents_merchant_status", "incidents", ["merchant_id", "status"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])

    # 8. analyst_actions
    op.create_table(
        "analyst_actions",
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("analyst_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("action_metadata", sa.JSON(), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analyst_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.incident_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("action_id"),
    )

    # 9. idempotency_records
    op.create_table(
        "idempotency_records",
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="processing"),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("record_id"),
    )
    op.create_index(
        "uq_idempotency_merchant_key",
        "idempotency_records",
        ["merchant_id", "idempotency_key"],
        unique=True,
    )
    op.create_index("ix_idempotency_expires", "idempotency_records", ["expires_at"])


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_table("analyst_actions")
    op.drop_table("incidents")
    op.drop_table("payout_requests")
    op.drop_table("risk_decisions")
    op.drop_table("security_events")
    op.drop_table("sessions")
    op.drop_table("users")
    op.drop_table("merchants")
