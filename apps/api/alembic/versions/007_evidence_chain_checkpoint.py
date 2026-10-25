"""add a durable evidence-chain head checkpoint and mutation guards

Revision ID: 007_evidence_chain_checkpoint
Revises: 006_honey_evidence
Create Date: 2026-10-25 01:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007_evidence_chain_checkpoint"
down_revision: str | None = "006_honey_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GENESIS_HASH = "0" * 64


def upgrade() -> None:
    op.create_table(
        "evidence_chain_head",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO evidence_chain_head (id, seq, hash) "
            "SELECT 1, COALESCE(MAX(seq), 0), "
            "COALESCE((SELECT hash FROM evidence_log ORDER BY seq DESC LIMIT 1), :genesis) "
            "FROM evidence_log"
        ).bindparams(genesis=GENESIS_HASH)
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_evidence_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'evidence records are append-only';
            END;
            $$
            """
        )
        for table in ("evidence_log", "evidence_payload"):
            op.execute(
                f"CREATE TRIGGER {table}_reject_update_delete "
                f"BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation()"
            )
            op.execute(
                f"CREATE TRIGGER {table}_reject_truncate "
                f"BEFORE TRUNCATE ON {table} "
                "FOR EACH STATEMENT EXECUTE FUNCTION reject_evidence_mutation()"
            )
            op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE {table} FROM PUBLIC")
    elif bind.dialect.name == "sqlite":
        for table in ("evidence_log", "evidence_payload"):
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_reject_{operation.lower()} "
                    f"BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'evidence records are append-only'); END"
                )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("evidence_log", "evidence_payload"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_truncate ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update_delete ON {table}")
        op.execute("DROP FUNCTION IF EXISTS reject_evidence_mutation()")
    elif bind.dialect.name == "sqlite":
        for table in ("evidence_log", "evidence_payload"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete")

    op.drop_table("evidence_chain_head")
