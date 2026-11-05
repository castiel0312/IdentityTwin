"""Authenticated SSE delivery backed by the transactional domain-event outbox."""

import asyncio
import json
import re
import time
from dataclasses import dataclass
from uuid import UUID

from starlette.requests import Request

from app.db.session import SessionLocal
from app.models.domain_event import DomainEvent, DomainEventCursor

_EVENT_ID_PATTERN = re.compile(r"^[0-9]{1,19}$")
_MAX_EVENT_ID = 9_223_372_036_854_775_807
_POLL_INTERVAL_SECONDS = 0.5
_HEARTBEAT_SECONDS = 15
_REPLAY_BATCH_SIZE = 100


@dataclass(frozen=True)
class StreamMessage:
    event_id: int
    event_type: str
    payload: dict

    def as_sse(self) -> str:
        body = json.dumps(self.payload, separators=(",", ":"), sort_keys=True)
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {body}\n\n"


def _read_events(merchant_id: UUID, after_event_id: int) -> tuple[list[DomainEvent], int | None, int]:
    with SessionLocal() as db:
        current_id = db.get(DomainEventCursor, merchant_id)
        current = current_id.last_event_id if current_id else 0
        oldest = db.query(DomainEvent.event_id).filter(
            DomainEvent.merchant_id == merchant_id
        ).order_by(DomainEvent.event_id.asc()).limit(1).scalar()
        rows = (
            db.query(DomainEvent)
            .filter(
                DomainEvent.merchant_id == merchant_id,
                DomainEvent.event_id > after_event_id,
            )
            .order_by(DomainEvent.event_id.asc())
            .limit(_REPLAY_BATCH_SIZE)
            .all()
        )
        return rows, oldest, current


def _valid_cursor(value: str) -> int:
    if not _EVENT_ID_PATTERN.fullmatch(value):
        raise ValueError("Last-Event-ID must be a non-negative decimal integer.")
    parsed = int(value)
    if parsed > _MAX_EVENT_ID:
        raise ValueError("Last-Event-ID exceeds the supported range.")
    return parsed


async def stream_domain_events(request: Request, merchant_id: UUID, after_event_id: int):
    """Stream ordered tenant events, recovering from retained outbox rows on reconnect."""
    cursor = after_event_id
    last_heartbeat = time.monotonic()
    while not await request.is_disconnected():
        rows, oldest_id, current_id = await asyncio.to_thread(_read_events, merchant_id, cursor)

        if cursor > current_id:
            cursor = current_id
            yield StreamMessage(
                cursor,
                "stream.reset",
                {"reason": "cursor_ahead", "current_event_id": str(current_id)},
            ).as_sse()
            continue

        if oldest_id is not None and cursor < oldest_id - 1:
            cursor = oldest_id - 1
            yield StreamMessage(
                cursor,
                "stream.reset",
                {"reason": "retention_gap", "oldest_event_id": str(oldest_id)},
            ).as_sse()
            continue
        if oldest_id is None and cursor < current_id:
            cursor = current_id
            yield StreamMessage(
                cursor,
                "stream.reset",
                {"reason": "retention_gap", "current_event_id": str(current_id)},
            ).as_sse()
            continue

        if rows:
            for row in rows:
                cursor = row.event_id
                yield StreamMessage(row.event_id, row.event_type, row.payload).as_sse()
            continue

        if time.monotonic() - last_heartbeat >= _HEARTBEAT_SECONDS:
            yield ": keep-alive\n\n"
            last_heartbeat = time.monotonic()
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
