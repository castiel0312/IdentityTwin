"""honey workspace, canary registry, and hash-chained evidence log

Revision ID: 006_honey_evidence
Revises: 005_agentic_commerce
Create Date: 2026-10-24 23:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "006_honey_evidence"
down_revision: Union[str, None] = "005_agentic_commerce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canaries",
        sa.Column("canary_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("identity_id", sa.Uuid(), nullable=True),
        sa.Column("merchant_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.Column("secret_value", sa.String(length=256), nullable=False),
        sa.Column("armed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("canary_id"),
        sa.UniqueConstraint("tag"),
    )
    op.create_index("ix_canaries_session_id", "canaries", ["session_id"])
    op.create_index("ix_canaries_kind", "canaries", ["kind"])
    op.create_index("ix_canaries_identity_id", "canaries", ["identity_id"])
    op.create_index("ix_canaries_merchant_id", "canaries", ["merchant_id"])
    op.create_index("ix_canaries_session_kind", "canaries", ["session_id", "kind"])
    op.create_index("ix_canaries_secret_value", "canaries", ["secret_value"])
    op.create_index("ix_canaries_secret_tag", "canaries", ["secret_value", "tag"])

    op.create_table(
        "evidence_log",
        sa.Column("seq", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_ref", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
        sa.UniqueConstraint("hash"),
    )
    op.create_index("ix_evidence_log_event_ref", "evidence_log", ["event_ref"])

    op.create_table(
        "evidence_payload",
        sa.Column("seq", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
    )

    op.create_table(
        "incident_seals",
        sa.Column("seal_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("start_seq", sa.BigInteger(), nullable=False),
        sa.Column("end_seq", sa.BigInteger(), nullable=False),
        sa.Column("head_hash", sa.String(length=64), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("seal_id"),
    )
    op.create_index("ix_incident_seals_incident_id", "incident_seals", ["incident_id"])
    op.create_index("ix_incident_seals_session_id", "incident_seals", ["session_id"])
    op.create_index("ix_incident_seals_merchant_id", "incident_seals", ["merchant_id"])


def downgrade() -> None:
    op.drop_index("ix_incident_seals_merchant_id", table_name="incident_seals")
    op.drop_index("ix_incident_seals_session_id", table_name="incident_seals")
    op.drop_index("ix_incident_seals_incident_id", table_name="incident_seals")
    op.drop_table("incident_seals")
    op.drop_table("evidence_payload")
    op.drop_index("ix_evidence_log_event_ref", table_name="evidence_log")
    op.drop_table("evidence_log")
    op.drop_index("ix_canaries_secret_tag", table_name="canaries")
    op.drop_index("ix_canaries_secret_value", table_name="canaries")
    op.drop_index("ix_canaries_session_kind", table_name="canaries")
    op.drop_index("ix_canaries_merchant_id", table_name="canaries")
    op.drop_index("ix_canaries_identity_id", table_name="canaries")
    op.drop_index("ix_canaries_kind", table_name="canaries")
    op.drop_index("ix_canaries_session_id", table_name="canaries")
    op.drop_table("canaries")
