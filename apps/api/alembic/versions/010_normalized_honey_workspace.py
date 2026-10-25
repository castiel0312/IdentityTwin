"""persist honey workspace resources in session-scoped tables

Revision ID: 010_normalized_honey_workspace
Revises: 009_incident_seals
Create Date: 2026-10-25 01:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010_normalized_honey_workspace"
down_revision: str | None = "009_incident_seals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOURCE_TABLES = (
    "merchant_profile",
    "balances",
    "customers",
    "invoices",
    "transactions",
    "payouts",
    "payees",
    "api_credentials",
    "activity_log",
)


def upgrade() -> None:
    bind = op.get_bind()
    schema = "honey" if bind.dialect.name == "postgresql" else None
    if schema:
        op.execute("CREATE SCHEMA IF NOT EXISTS honey")

    for table_name in _RESOURCE_TABLES:
        op.create_table(
            table_name,
            sa.Column("session_id", sa.String(length=128), nullable=False),
            sa.Column("identity_id", sa.String(length=128), nullable=False),
            sa.Column("resource_id", sa.String(length=128), nullable=False),
            sa.Column("synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("data", sa.JSON(), nullable=False),
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
            sa.PrimaryKeyConstraint("session_id", "identity_id", "resource_id"),
            schema=schema,
        )
        op.create_index(
            f"ix_{table_name}_identity_id",
            table_name,
            ["identity_id"],
            schema=schema,
        )

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'honey_rw') THEN
                    GRANT USAGE ON SCHEMA honey TO honey_rw;
                    GRANT SELECT, INSERT, UPDATE, DELETE
                        ON ALL TABLES IN SCHEMA honey TO honey_rw;
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    schema = "honey" if op.get_bind().dialect.name == "postgresql" else None
    for table_name in reversed(_RESOURCE_TABLES):
        op.drop_index(
            f"ix_{table_name}_identity_id",
            table_name=table_name,
            schema=schema,
        )
        op.drop_table(table_name, schema=schema)
