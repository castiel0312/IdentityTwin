import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.models.event import SecurityEvent
    from app.models.payout import PayoutRequestRecord
    from app.models.principal import Merchant, User
    from app.models.risk import RiskDecisionRecord

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utc_now


class SessionRecord(Base, TimestampMixin):
    __tablename__ = "sessions"

    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("merchants.merchant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trust_level: Mapped[str] = mapped_column(String(32), default="NORMAL", nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    device_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="sessions")
    user: Mapped["User"] = relationship("User", back_populates="sessions")
    events: Mapped[list["SecurityEvent"]] = relationship("SecurityEvent", back_populates="session")
    decisions: Mapped[list["RiskDecisionRecord"]] = relationship(
        "RiskDecisionRecord", back_populates="session"
    )
    payouts: Mapped[list["PayoutRequestRecord"]] = relationship(
        "PayoutRequestRecord", back_populates="session"
    )

    __table_args__ = (
        Index("ix_sessions_merchant_user", "merchant_id", "user_id"),
        Index("ix_sessions_trust_level", "trust_level"),
    )
