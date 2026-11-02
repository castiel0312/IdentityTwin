"""add tenant scope columns to the evidence chain for bounded queries

Revision ID: 015_evidence_scope_columns
Revises: 014_investigations
Create Date: 2026-11-02 00:10:00.000000

The AI Investigator must never scan the global evidence chain. These columns
denormalize the session/merchant scope already present in each payload so the
chain can be filtered and bounded in SQL. They are not part of the hash chain
itself; integrity remains anchored by seq/event_ref/payload_hash/prev_hash.
"""

import json
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "015_evidence_scope_columns"
down_revision: str | None = "014_investigations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_GUARD_TRIGGERS = (
    "evidence_log_reject_update",
    "evidence_log_reject_delete",
)


def _as_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _parse_payload(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def upgrade() -> None:
    op.add_column("evidence_log", sa.Column("session_id", sa.Uuid(), nullable=True))
    op.add_column("evidence_log", sa.Column("merchant_id", sa.Uuid(), nullable=True))

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        for trigger in _SQLITE_GUARD_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    elif dialect == "postgresql":
        op.execute("ALTER TABLE evidence_log DISABLE TRIGGER USER")

    evidence_log = sa.table(
        "evidence_log",
        sa.column("seq", sa.BigInteger()),
        sa.column("session_id", sa.Uuid()),
        sa.column("merchant_id", sa.Uuid()),
    )
    sessions = sa.table(
        "sessions",
        sa.column("session_id", sa.Uuid()),
        sa.column("merchant_id", sa.Uuid()),
    )

    rows = bind.execute(sa.text("SELECT seq, payload FROM evidence_payload")).fetchall()
    for seq, raw_payload in rows:
        payload = _parse_payload(raw_payload)
        session_uuid = _as_uuid(payload.get("session_id"))
        merchant_uuid = _as_uuid(payload.get("merchant_id"))
        if merchant_uuid is None and session_uuid is not None:
            merchant_uuid = bind.execute(
                sa.select(sessions.c.merchant_id).where(
                    sessions.c.session_id == session_uuid
                )
            ).scalar_one_or_none()
        if session_uuid is None and merchant_uuid is None:
            continue
        bind.execute(
            evidence_log.update()
            .where(evidence_log.c.seq == seq)
            .values(session_id=session_uuid, merchant_id=merchant_uuid)
        )

    if dialect == "sqlite":
        for table in ("evidence_log",):
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_reject_{operation.lower()} "
                    f"BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'evidence records are append-only'); END"
                )
    elif dialect == "postgresql":
        op.execute("ALTER TABLE evidence_log ENABLE TRIGGER USER")

    op.create_index("ix_evidence_log_session_id", "evidence_log", ["session_id"])
    op.create_index("ix_evidence_log_merchant_id", "evidence_log", ["merchant_id"])
    op.create_index(
        "ix_evidence_log_scope_seq",
        "evidence_log",
        ["session_id", "merchant_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_log_scope_seq", table_name="evidence_log")
    op.drop_index("ix_evidence_log_merchant_id", table_name="evidence_log")
    op.drop_index("ix_evidence_log_session_id", table_name="evidence_log")
    op.drop_column("evidence_log", "merchant_id")
    op.drop_column("evidence_log", "session_id")
