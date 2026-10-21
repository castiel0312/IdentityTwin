import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from app.models.session import SessionRecord

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utc_now


class SecurityEvent(Base, TimestampMixin):
    __tablename__ = "security_events"

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("merchants.merchant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    server_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    processed_by_risk_engine: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    session: Mapped["SessionRecord"] = relationship("SessionRecord", back_populates="events")

    __table_args__ = (
        Index("ix_security_events_occurred", "occurred_at"),
        Index("ix_security_events_merchant_type", "merchant_id", "event_type"),
    )
