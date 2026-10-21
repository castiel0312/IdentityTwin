"""add step_up_challenges

Revision ID: 002_step_up_challenges
Revises: 001_initial_schema
Create Date: 2026-10-21 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_step_up_challenges"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "step_up_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_step_up_challenges_session_id", "step_up_challenges", ["session_id"])
    op.create_index("ix_step_up_challenges_merchant_id", "step_up_challenges", ["merchant_id"])
    op.create_index("ix_step_up_session_merchant", "step_up_challenges", ["session_id", "merchant_id"])


def downgrade() -> None:
    op.drop_index("ix_step_up_session_merchant", table_name="step_up_challenges")
    op.drop_index("ix_step_up_challenges_merchant_id", table_name="step_up_challenges")
    op.drop_index("ix_step_up_challenges_session_id", table_name="step_up_challenges")
    op.drop_table("step_up_challenges")
