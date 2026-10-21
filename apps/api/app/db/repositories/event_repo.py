from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event import SecurityEvent


class EventRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, event: SecurityEvent) -> SecurityEvent:
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_recent_by_session(self, session_id: UUID, limit: int = 50) -> list[SecurityEvent]:
        stmt = (
            select(SecurityEvent)
            .where(SecurityEvent.session_id == session_id)
            .order_by(SecurityEvent.occurred_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_by_idempotency_key(
        self, merchant_id: UUID, idempotency_key: str
    ) -> SecurityEvent | None:
        stmt = select(SecurityEvent).where(
            SecurityEvent.merchant_id == merchant_id,
            SecurityEvent.idempotency_key == idempotency_key,
        )
        return self.db.scalars(stmt).first()
