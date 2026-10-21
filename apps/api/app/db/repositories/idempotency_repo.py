from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateRequestException
from app.models.idempotency import IdempotencyRecord


class IdempotencyRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_record(self, merchant_id: UUID, idempotency_key: str) -> IdempotencyRecord | None:
        stmt = select(IdempotencyRecord).where(
            IdempotencyRecord.merchant_id == merchant_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        record = self.db.scalars(stmt).first()
        if record:
            expires = record.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < datetime.now(timezone.utc):
                return None
        return record

    def save_record(self, record: IdempotencyRecord) -> IdempotencyRecord:
        try:
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
            return record
        except IntegrityError:
            self.db.rollback()
            raise DuplicateRequestException(
                message="A request with this idempotency key is already processing or has completed.",
                code="IDEMPOTENCY_KEY_COLLISION",
            ) from None

    def update_record(
        self,
        record: IdempotencyRecord,
        status: str,
        response_code: int,
        response_payload: dict[str, Any],
    ) -> IdempotencyRecord:
        record.status = status
        record.response_code = response_code
        record.response_payload = response_payload
        self.db.commit()
        self.db.refresh(record)
        return record
