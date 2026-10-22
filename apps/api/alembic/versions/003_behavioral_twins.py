"""add behavioral twins and session risk state

Revision ID: 003_behavioral_twins
Revises: 002_step_up_challenges
Create Date: 2026-10-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_behavioral_twins"
down_revision: Union[str, None] = "002_step_up_challenges"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "behavioral_twins",
        sa.Column("twin_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_devices", sa.JSON(), nullable=False),
        sa.Column("confirmed_locations", sa.JSON(), nullable=False),
        sa.Column("payee_observations", sa.JSON(), nullable=False),
        sa.Column("device_observations", sa.JSON(), nullable=False),
        sa.Column("location_observations", sa.JSON(), nullable=False),
        sa.Column("hour_histogram", sa.JSON(), nullable=False),
        sa.Column("total_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("amount_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("twin_id"),
    )
    op.create_index(
        "ix_behavioral_twins_merchant_id", "behavioral_twins", ["merchant_id"]
    )
    op.create_index("ix_behavioral_twins_user_id", "behavioral_twins", ["user_id"])
    op.create_index(
        "uq_behavioral_twins_merchant_user",
        "behavioral_twins",
        ["merchant_id", "user_id"],
        unique=True,
    )

    op.create_table(
        "session_risk_state",
        sa.Column("state_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("carried_forward", sa.Float(), nullable=False, server_default="0"),
        sa.Column("raw_points_sum", sa.Float(), nullable=False, server_default="0"),
        sa.Column("decay_points_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("current_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("canary_points", sa.Float(), nullable=False, server_default="0"),
        sa.Column("contributions", sa.JSON(), nullable=False),
        sa.Column("latched_signals", sa.JSON(), nullable=False),
        sa.Column("fired_payees", sa.JSON(), nullable=False),
        sa.Column("registered_payees", sa.JSON(), nullable=False),
        sa.Column("sequence_markers", sa.JSON(), nullable=False),
        sa.Column("consumed_markers", sa.JSON(), nullable=False),
        sa.Column("event_fingerprints", sa.JSON(), nullable=False),
        sa.Column("canary_seen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_id"),
    )
    op.create_index(
        "ix_session_risk_state_session_id", "session_risk_state", ["session_id"], unique=True
    )
    op.create_index(
        "ix_session_risk_state_merchant_id", "session_risk_state", ["merchant_id"]
    )
    op.create_index("ix_session_risk_state_user_id", "session_risk_state", ["user_id"])
    op.create_index(
        "ix_session_risk_state_merchant_user",
        "session_risk_state",
        ["merchant_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_risk_state_merchant_user", table_name="session_risk_state")
    op.drop_index("ix_session_risk_state_user_id", table_name="session_risk_state")
    op.drop_index("ix_session_risk_state_merchant_id", table_name="session_risk_state")
    op.drop_index("ix_session_risk_state_session_id", table_name="session_risk_state")
    op.drop_table("session_risk_state")

    op.drop_index("uq_behavioral_twins_merchant_user", table_name="behavioral_twins")
    op.drop_index("ix_behavioral_twins_user_id", table_name="behavioral_twins")
    op.drop_index("ix_behavioral_twins_merchant_id", table_name="behavioral_twins")
    op.drop_table("behavioral_twins")
