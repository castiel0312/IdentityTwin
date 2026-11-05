"""Transactional, tenant-scoped outbox for user-visible domain changes."""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, event, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session as OrmSession

from app.models.domain_event import DomainEvent, DomainEventCursor
from app.models.incident import IncidentRecord

_EVENT_TYPES = {
    "security_events": "behavioral.event",
    "risk_decisions": "risk.decision",
    "payout_requests": "payout.changed",
    "sessions": "session.changed",
    "incidents": "incident.changed",
    "vaccination_matches": "vaccination.match",
    "vaccination_signatures": "vaccination.signature",
    "evidence_log": "evidence.appended",
    "incident_seals": "evidence.sealed",
    "investigations": "investigation.changed",
    "analyst_actions": "analyst.workflow",
    "intent_profiles": "analyst.workflow",
}
_EVENT_ORDER = {
    "behavioral.event": 0,
    "risk.decision": 1,
    "session.changed": 2,
    "payout.changed": 3,
    "incident.changed": 4,
    "vaccination.match": 5,
    "vaccination.signature": 6,
    "evidence.appended": 7,
    "evidence.sealed": 8,
    "investigation.changed": 9,
    "analyst.workflow": 10,
}
_PENDING_KEY = "identitytwin_pending_domain_events"
_RETENTION_DAYS = 30


def _tenant_id(obj: Any) -> UUID | None:
    value = (
        getattr(obj, "merchant_id", None)
        or getattr(obj, "target_merchant_id", None)
        or getattr(obj, "source_merchant_id", None)
    )
    return value if isinstance(value, UUID) else None


def _primary_key(obj: Any) -> str | None:
    identity = inspect(obj).identity
    if identity:
        return str(identity[0])
    mapper = inspect(obj).mapper
    if len(mapper.primary_key) == 1:
        value = getattr(obj, mapper.primary_key[0].key, None)
        return str(value) if value is not None else None
    return None


def _capture_changes(session: OrmSession, _flush_context: Any, _instances: Any) -> None:
    pending: dict[int, tuple[Any, str, str, UUID | None]] = {}
    for collection, operation in (
        (session.new, "created"),
        (session.dirty, "updated"),
        (session.deleted, "deleted"),
    ):
        for obj in collection:
            table_name = getattr(getattr(obj, "__table__", None), "name", None)
            event_type = _EVENT_TYPES.get(table_name)
            if event_type is None or (
                operation == "updated" and not session.is_modified(obj, include_collections=False)
            ):
                continue
            pending[id(obj)] = (obj, event_type, operation, _tenant_id(obj))
    if pending:
        session.info.setdefault(_PENDING_KEY, []).extend(pending.values())


def _increment_cursor(session: OrmSession, merchant_id: UUID) -> int:
    dialect = session.get_bind().dialect.name
    values = {"merchant_id": merchant_id, "last_event_id": 0}
    connection = session.connection()
    if dialect == "postgresql":
        stmt = postgres_insert(DomainEventCursor.__table__).values(**values).on_conflict_do_nothing(
            index_elements=[DomainEventCursor.__table__.c.merchant_id]
        )
    elif dialect == "sqlite":
        stmt = sqlite_insert(DomainEventCursor.__table__).values(**values).on_conflict_do_nothing(
            index_elements=[DomainEventCursor.__table__.c.merchant_id]
        )
    else:
        raise RuntimeError(f"Domain event cursor does not support database dialect {dialect}.")
    connection.execute(stmt)
    cursor_table = DomainEventCursor.__table__
    result = connection.execute(
        cursor_table.update()
        .where(cursor_table.c.merchant_id == merchant_id)
        .values(last_event_id=cursor_table.c.last_event_id + 1)
        .returning(cursor_table.c.last_event_id)
    )
    return result.scalar_one()


def _resolve_tenant(session: OrmSession, obj: Any, tenant_id: UUID | None) -> UUID | None:
    if tenant_id is not None:
        return tenant_id
    incident_id = getattr(obj, "incident_id", None)
    if incident_id is None:
        return None
    return session.scalar(
        select(IncidentRecord.merchant_id).where(IncidentRecord.incident_id == incident_id)
    )


def _write_events(session: OrmSession, _flush_context: Any) -> None:
    pending = session.info.pop(_PENDING_KEY, [])
    pending.sort(
        key=lambda item: (
            _EVENT_ORDER[item[1]],
            str(getattr(item[0], "session_id", "")),
            _primary_key(item[0]) or "",
        )
    )
    for obj, event_type, operation, tenant_id in pending:
        merchant_id = _resolve_tenant(session, obj, tenant_id)
        entity_id = _primary_key(obj)
        if merchant_id is None or entity_id is None:
            continue
        session_id = getattr(obj, "session_id", None)
        payload = {
            "schema_version": 1,
            "entity_type": obj.__table__.name,
            "entity_id": entity_id,
            "session_id": str(session_id) if session_id is not None else None,
            "operation": operation,
        }
        incident_id = getattr(obj, "incident_id", None)
        if incident_id is not None:
            payload["incident_id"] = str(incident_id)
        safe_fields = {
            "payout_requests": ("status", "provider_name"),
            "risk_decisions": ("risk_score", "trust_level", "action", "routing_destination"),
            "sessions": ("status", "risk_score", "trust_level"),
            "incidents": ("status", "severity"),
            "vaccination_matches": ("match_score", "risk_points"),
            "vaccination_signatures": ("status",),
            "investigations": ("status", "ai_used"),
        }.get(obj.__table__.name, ())
        payload.update(
            {
                name: getattr(obj, name)
                for name in safe_fields
                if getattr(obj, name, None) is not None
            }
        )
        session.add(
            DomainEvent(
                merchant_id=merchant_id,
                event_id=_increment_cursor(session, merchant_id),
                event_type=event_type,
                entity_type=obj.__table__.name,
                entity_id=entity_id,
                operation=operation,
                payload=payload,
            )
        )


event.listen(OrmSession, "before_flush", _capture_changes)
event.listen(OrmSession, "after_flush_postexec", _write_events)


def prune_expired_domain_events(now: datetime | None = None) -> int:
    """Apply the documented 30-day event retention policy."""
    from app.db.session import SessionLocal

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=_RETENTION_DAYS)
    with SessionLocal.begin() as db:
        result = db.execute(delete(DomainEvent).where(DomainEvent.created_at < cutoff))
        return result.rowcount or 0
