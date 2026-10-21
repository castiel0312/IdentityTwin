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
