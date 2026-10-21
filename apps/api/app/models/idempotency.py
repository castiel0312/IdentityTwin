import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class IdempotencyRecord(Base, TimestampMixin):
    __tablename__ = "idempotency_records"

    record_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    merchant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.merchant_id", ondelete="CASCADE"), nullable=False
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="processing", nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("uq_idempotency_merchant_key", "merchant_id", "idempotency_key", unique=True),
        Index("ix_idempotency_expires", "expires_at"),
    )
