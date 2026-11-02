from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.intent import IntentProfileRecord


class IntentProfileRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, record: IntentProfileRecord) -> IntentProfileRecord:
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, profile_id: UUID, merchant_id: UUID) -> IntentProfileRecord | None:
        return self.db.scalar(
            select(IntentProfileRecord).where(
                IntentProfileRecord.profile_id == profile_id,
                IntentProfileRecord.merchant_id == merchant_id,
            )
        )

    def list_for_session(
        self,
        merchant_id: UUID,
        session_id: UUID,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[IntentProfileRecord], int]:
        filters = [
            IntentProfileRecord.merchant_id == merchant_id,
            IntentProfileRecord.session_id == session_id,
        ]
        total = (
            self.db.scalar(select(func.count()).select_from(IntentProfileRecord).where(*filters))
            or 0
        )
        items = list(
            self.db.scalars(
                select(IntentProfileRecord)
                .where(*filters)
                .order_by(
                    IntentProfileRecord.created_at.desc(),
                    IntentProfileRecord.profile_id.desc(),
                )
                .limit(limit)
                .offset(offset)
            ).all()
        )
        return items, total
