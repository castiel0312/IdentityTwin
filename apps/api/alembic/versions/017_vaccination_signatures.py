"""persist security vaccination signatures and cross-merchant matches

Revision ID: 017_vaccination_signatures
Revises: 016_intent_profiles
Create Date: 2026-11-04 00:00:00.000000

Security Vaccination: behavioral attack signatures are extracted from confirmed
attacks, approved by an authorized analyst, then applied deterministically to
protect other merchants from the same attack pattern.

Signatures contain only normalized, reproducible behavioral patterns (event
sequence, feature flags, risk indicators). They never contain passwords, access
tokens, PayPal credentials, raw customer financial data, or unnecessary PII.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "017_vaccination_signatures"
down_revision: str | None = "016_intent_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vaccination_signatures",
        sa.Column("signature_id", sa.Uuid(), nullable=False),
        sa.Column("source_merchant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("signature_definition", sa.JSON(), nullable=False),
        sa.Column("detection_confidence", sa.Float(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            ["source_merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("signature_id"),
        sa.CheckConstraint(
            "status IN ('PROPOSED', 'ACTIVE', 'REVOKED')",
            name="ck_vaccination_signature_status",
        ),
        sa.CheckConstraint(
            "detection_confidence >= 0.0 AND detection_confidence <= 100.0",
            name="ck_vaccination_signature_confidence_range",
        ),
    )
    op.create_index("ix_vaccination_signatures_source_merchant", "vaccination_signatures", ["source_merchant_id"])
    op.create_index("ix_vaccination_signatures_status", "vaccination_signatures", ["status"])
    op.create_index(
        "ix_vaccination_signatures_source_status",
        "vaccination_signatures",
        ["source_merchant_id", "status"],
    )

    op.create_table(
        "vaccination_matches",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("signature_id", sa.Uuid(), nullable=False),
        sa.Column("target_merchant_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("match_reason", sa.Text(), nullable=False),
        sa.Column("matched_features", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("risk_points", sa.Float(), nullable=False, server_default="0"),
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
            ["signature_id"], ["vaccination_signatures.signature_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("match_id"),
    )
    op.create_index("ix_vaccination_matches_signature", "vaccination_matches", ["signature_id"])
    op.create_index("ix_vaccination_matches_target_merchant", "vaccination_matches", ["target_merchant_id"])
    op.create_index(
        "ix_vaccination_matches_target_created",
        "vaccination_matches",
        ["target_merchant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_vaccination_matches_target_created", table_name="vaccination_matches")
    op.drop_index("ix_vaccination_matches_target_merchant", table_name="vaccination_matches")
    op.drop_index("ix_vaccination_matches_signature", table_name="vaccination_matches")
    op.drop_table("vaccination_matches")
    op.drop_index("ix_vaccination_signatures_source_status", table_name="vaccination_signatures")
    op.drop_index("ix_vaccination_signatures_status", table_name="vaccination_signatures")
    op.drop_index("ix_vaccination_signatures_source_merchant", table_name="vaccination_signatures")
    op.drop_table("vaccination_signatures")
