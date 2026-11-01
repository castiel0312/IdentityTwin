import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from app.models.risk import RiskDecisionRecord
    from app.models.session import SessionRecord

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class PayoutRequestRecord(Base, TimestampMixin):
    __tablename__ = "payout_requests"

    payout_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    decision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("risk_decisions.decision_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
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
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    reference_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sender_batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sender_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ------------------------------------------------------------------
    # Automated reconciliation tracking (P3 background worker).
    # ------------------------------------------------------------------
    reconciliation_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Persisted atomic claim marker used by the reconciliation worker. Set by
    # the claiming UPDATE so a claim survives the internal commit performed by
    # reconcile_payout(). Multiple workers never process the same payout.
    reconciliation_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    session: Mapped["SessionRecord"] = relationship("SessionRecord", back_populates="payouts")
    decision: Mapped["RiskDecisionRecord"] = relationship(
        "RiskDecisionRecord", back_populates="payout"
    )

    __table_args__ = (
        Index("ix_payouts_merchant_idempotency", "merchant_id", "idempotency_key"),
        Index("ix_payouts_status", "status"),
        Index("ix_payouts_provider_batch_id", "provider_batch_id"),
        Index("ix_payouts_next_retry", "next_retry_at"),
        Index("ix_payouts_reconciliation", "status", "next_retry_at", "escalated_at"),
    )
