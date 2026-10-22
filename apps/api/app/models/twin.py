import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from app.models.principal import Merchant, User
    from app.models.session import SessionRecord

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utc_now


class BehavioralTwin(Base, TimestampMixin):
    """Persistent behavioural baseline for one identity (merchant + user)."""

    __tablename__ = "behavioral_twins"

    twin_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed_devices: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confirmed_locations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    payee_observations: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    device_observations: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    location_observations: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    hour_histogram: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=True
    )

    merchant: Mapped["Merchant"] = relationship("Merchant")
    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index(
            "uq_behavioral_twins_merchant_user",
            "merchant_id",
            "user_id",
            unique=True,
        ),
    )


class SessionRiskStateRecord(Base, TimestampMixin):
    """Durable per-session risk ledger maintained by the risk engine."""

    __tablename__ = "session_risk_state"

    state_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
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
    carried_forward: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    raw_points_sum: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    decay_points_total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    canary_points: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    contributions: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    latched_signals: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    fired_payees: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    registered_payees: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    sequence_markers: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    consumed_markers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    event_fingerprints: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    canary_seen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=True
    )

    session: Mapped["SessionRecord"] = relationship("SessionRecord")

    __table_args__ = (Index("ix_session_risk_state_merchant_user", "merchant_id", "user_id"),)
