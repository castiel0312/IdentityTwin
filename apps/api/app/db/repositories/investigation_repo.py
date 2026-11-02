from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.investigation import InvestigationRecord


class InvestigationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, record: InvestigationRecord) -> InvestigationRecord:
        # Flush only; the service owns the transaction boundary so unrelated
        # pending state is never committed by repository internals.
        self.db.add(record)
        self.db.flush()
        return record

    def get(
        self, investigation_id: UUID, merchant_id: UUID
    ) -> InvestigationRecord | None:
        return self.db.scalar(
            select(InvestigationRecord).where(
                InvestigationRecord.investigation_id == investigation_id,
                InvestigationRecord.merchant_id == merchant_id,
            )
        )

    def list_for_incident(
        self,
        merchant_id: UUID,
        incident_id: UUID,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[InvestigationRecord], int]:
        filters = [
            InvestigationRecord.merchant_id == merchant_id,
            InvestigationRecord.incident_id == incident_id,
        ]
        total = (
            self.db.scalar(
                select(func.count())
                .select_from(InvestigationRecord)
                .where(*filters)
            )
            or 0
        )
        items = list(
            self.db.scalars(
                select(InvestigationRecord)
                .where(*filters)
                .order_by(InvestigationRecord.created_at.desc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
        return items, total
