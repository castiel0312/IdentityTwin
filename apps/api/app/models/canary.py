import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CanaryRecord(Base, TimestampMixin):
    __tablename__ = "canaries"

    canary_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    identity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    merchant_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    tag: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    secret_value: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    armed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trigger_meta: Mapped[dict[str, Any]] = mapped_column(
        __import__("sqlalchemy").JSON, default=dict, nullable=False
    )

    __table_args__ = (
        Index("ix_canaries_session_kind", "session_id", "kind"),
        Index("ix_canaries_secret_tag", "secret_value", "tag"),
        UniqueConstraint("session_id", "kind", name="uq_canaries_session_kind"),
    )
