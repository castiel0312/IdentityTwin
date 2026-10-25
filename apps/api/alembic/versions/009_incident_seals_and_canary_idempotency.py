"""record incident sealing and enforce one canary per session/kind

Revision ID: 009_incident_seals
Revises: 008_persist_honey_workspace
Create Date: 2026-10-25 01:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009_incident_seals"
down_revision: str | None = "008_persist_honey_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_canaries_session_kind",
        "canaries",
        ["session_id", "kind"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_canaries_session_kind", table_name="canaries")
    op.drop_column("incidents", "sealed_at")
