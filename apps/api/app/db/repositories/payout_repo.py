from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payout import PayoutRequestRecord
from app.models.risk import RiskDecisionRecord


class PayoutRepository:
    def __init__(self, db: Session):
        self.db = db

    def save_decision(self, decision: RiskDecisionRecord) -> RiskDecisionRecord:
        self.db.add(decision)
        self.db.commit()
        self.db.refresh(decision)
        return decision

    def create(self, payout: PayoutRequestRecord) -> PayoutRequestRecord:
        self.db.add(payout)
        self.db.commit()
        self.db.refresh(payout)
        return payout

    def get_by_id(self, payout_id: UUID) -> PayoutRequestRecord | None:
        stmt = select(PayoutRequestRecord).where(PayoutRequestRecord.payout_id == payout_id)
        return self.db.scalars(stmt).first()

    def get_by_idempotency_key(
        self, merchant_id: UUID, idempotency_key: str
    ) -> PayoutRequestRecord | None:
        stmt = select(PayoutRequestRecord).where(
            PayoutRequestRecord.merchant_id == merchant_id,
            PayoutRequestRecord.idempotency_key == idempotency_key,
        )
        return self.db.scalars(stmt).first()
