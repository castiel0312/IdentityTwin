import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utc_now


class IncidentRecord(Base, TimestampMixin):
    __tablename__ = "incidents"

    incident_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    merchant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("merchants.merchant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="HIGH", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=75.0, nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    actions: Mapped[list["AnalystActionRecord"]] = relationship(
        "AnalystActionRecord", back_populates="incident", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_incidents_merchant_status", "merchant_id", "status"),
        Index("ix_incidents_severity", "severity"),
    )


class AnalystActionRecord(Base, TimestampMixin):
    __tablename__ = "analyst_actions"

    action_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("incidents.incident_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analyst_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    action_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    incident: Mapped["IncidentRecord"] = relationship("IncidentRecord", back_populates="actions")
