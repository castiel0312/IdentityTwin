import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

if TYPE_CHECKING:
    from app.models.payout import PayoutRequestRecord
    from app.models.session import SessionRecord

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utc_now


class RiskDecisionRecord(Base, TimestampMixin):
    __tablename__ = "risk_decisions"

    decision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
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
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    trust_level: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    routing_destination: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    risk_signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    session: Mapped["SessionRecord"] = relationship("SessionRecord", back_populates="decisions")
    payout: Mapped[Optional["PayoutRequestRecord"]] = relationship(
        "PayoutRequestRecord", back_populates="decision", uselist=False
    )

    __table_args__ = (Index("ix_risk_decisions_merchant_eval", "merchant_id", "evaluated_at"),)
