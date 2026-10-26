from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
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
        *,
        q: str | None = None,
        status: str | None = None,
        trust_level: str | None = None,
        user_id: UUID | None = None,
        sort: str = "-last_activity_at",
    ) -> tuple[list[SessionRecord], int]:
        filters = [SessionRecord.merchant_id == merchant_id]
        if status:
            filters.append(SessionRecord.status == status.strip().lower())
        if trust_level:
            filters.append(SessionRecord.trust_level == trust_level.strip().upper())
        if user_id:
            filters.append(SessionRecord.user_id == user_id)
        if q:
            term = f"%{q.strip()}%"
            filters.append(
                or_(
                    cast(SessionRecord.session_id, String).ilike(term),
                    SessionRecord.device_fingerprint.ilike(term),
                    SessionRecord.ip_address.ilike(term),
                )
            )

        total = (
            self.db.scalar(
                select(func.count()).select_from(SessionRecord).where(*filters)
            )
            or 0
        )

        descending = sort.startswith("-")
        key = sort.lstrip("-")
        if key == "risk_score":
            column = SessionRecord.risk_score
        elif key == "created_at":
            column = SessionRecord.created_at
        elif key == "status":
            column = SessionRecord.status
        else:
            column = SessionRecord.last_activity_at
        ordering = column.desc() if descending else column.asc()

        stmt = (
            select(SessionRecord)
            .where(*filters)
            .order_by(ordering)
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
