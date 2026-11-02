import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class IntentProfileRecord(Base, TimestampMixin):
    """Persisted, merchant-scoped advisory intent profile snapshot.

    The row stores a bounded, immutable read-model produced by the deterministic
    profiler. It never participates in risk scoring, routing, access control or
    payment execution.
    """

    __tablename__ = "intent_profiles"

    profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    merchant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("merchants.merchant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    ai_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bundle: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        Index("ix_intent_profiles_merchant_created", "merchant_id", "created_at"),
        Index("ix_intent_profiles_session_created", "session_id", "created_at"),
    )
