"""persist synthetic honey workspace state in the isolated schema

Revision ID: 008_persist_honey_workspace
Revises: 007_evidence_chain_checkpoint
Create Date: 2026-10-25 01:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008_persist_honey_workspace"
down_revision: str | None = "007_evidence_chain_checkpoint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE SCHEMA IF NOT EXISTS honey")
        honey_schema = "honey"
    else:
        honey_schema = None

    op.create_table(
        "workspace_state",
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("identity_id", sa.String(length=128), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("world", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("session_id"),
        schema=honey_schema,
    )
    op.create_index(
        "ix_honey_workspace_state_identity_id",
        "workspace_state",
        ["identity_id"],
        schema=honey_schema,
    )

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'honey_rw') THEN
                    GRANT USAGE ON SCHEMA honey TO honey_rw;
                    GRANT SELECT, INSERT, UPDATE ON TABLE honey.workspace_state TO honey_rw;
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    honey_schema = "honey" if op.get_bind().dialect.name == "postgresql" else None
    op.drop_index(
        "ix_honey_workspace_state_identity_id",
        table_name="workspace_state",
        schema=honey_schema,
    )
    op.drop_table("workspace_state", schema=honey_schema)
