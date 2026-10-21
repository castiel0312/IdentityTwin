from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.session import SessionRecord


class SessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, session_id: UUID, for_update: bool = False) -> SessionRecord | None:
        stmt = select(SessionRecord).where(SessionRecord.session_id == session_id)
        if for_update:
            stmt = stmt.with_for_update()
        return self.db.scalars(stmt).first()

    def list_by_merchant(
        self,
        merchant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SessionRecord], int]:
        total_stmt = (
            select(func.count())
            .select_from(SessionRecord)
            .where(SessionRecord.merchant_id == merchant_id)
        )
        total = self.db.scalar(total_stmt) or 0

        stmt = (
            select(SessionRecord)
            .where(SessionRecord.merchant_id == merchant_id)
            .order_by(SessionRecord.last_activity_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list(self.db.scalars(stmt).all())
        return items, total

    def create(self, session: SessionRecord) -> SessionRecord:
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def update_trust_state(
        self,
        session_id: UUID,
        trust_level: str,
        risk_score: float,
    ) -> SessionRecord | None:
        session = self.get_by_id(session_id)
        if session:
            session.trust_level = trust_level
            session.risk_score = risk_score
            session.last_activity_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(session)
        return session

    def update_activity(self, session_id: UUID) -> None:
        session = self.get_by_id(session_id)
        if session:
            session.last_activity_at = datetime.now(timezone.utc)
            self.db.commit()
