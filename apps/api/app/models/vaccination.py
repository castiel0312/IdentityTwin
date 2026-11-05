"""Security Vaccination models.

A vaccination signature is a normalized, reproducible behavioral pattern
extracted from a confirmed attack. Signatures follow the lifecycle
PROPOSED -> ACTIVE -> REVOKED. Only ACTIVE signatures are applied when
evaluating another merchant's events. A signature never independently
authorizes a payment or bypasses the Trust Gateway; it feeds an additional
explainable risk signal into the existing deterministic risk engine.

Signature definitions contain only sanitized behavioral data: event sequences,
feature flags, risk indicators, and hashed identifiers. They never contain
passwords, access tokens, PayPal credentials, raw customer financial data, or
unnecessary PII.
"""

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utc_now


class VaccinationSignature(Base, TimestampMixin):
    """A behavioral attack signature extracted from a confirmed attack."""

    __tablename__ = "vaccination_signatures"

    signature_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_merchant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("merchants.merchant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature_definition: Mapped[dict[str, Any]] = mapped_column(
        __import__("sqlalchemy").JSON, nullable=False
    )
    detection_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_refs: Mapped[list[int]] = mapped_column(
        __import__("sqlalchemy").JSON, default=list, nullable=False, server_default="[]"
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    matches: Mapped[list["VaccinationMatch"]] = relationship(
        "VaccinationMatch", back_populates="signature", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PROPOSED', 'ACTIVE', 'REVOKED')",
            name="ck_vaccination_signature_status",
        ),
        CheckConstraint(
            "detection_confidence >= 0.0 AND detection_confidence <= 100.0",
            name="ck_vaccination_signature_confidence_range",
        ),
        Index("ix_vaccination_signatures_source_status", "source_merchant_id", "status"),
    )


class VaccinationMatch(Base, TimestampMixin):
    """A recorded match between a merchant's events and an active signature."""

    __tablename__ = "vaccination_matches"

    match_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signature_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("vaccination_signatures.signature_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_merchant_id: Mapped[UUID] = mapped_column(
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
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    match_reason: Mapped[str] = mapped_column(Text, nullable=False)
    matched_features: Mapped[dict[str, Any]] = mapped_column(
        __import__("sqlalchemy").JSON, default=dict, nullable=False, server_default="{}"
    )
    evidence_refs: Mapped[list[int]] = mapped_column(
        __import__("sqlalchemy").JSON, default=list, nullable=False, server_default="[]"
    )
    risk_points: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")

    signature: Mapped["VaccinationSignature"] = relationship(
        "VaccinationSignature", back_populates="matches"
    )

    @property
    def signature_name(self) -> str:
        """Human-readable signature name for API serialization.

        Resolved through the signature relationship so VaccinationMatchResponse
        (from_attributes=True) can populate signature_name without a column.
        """
        return self.signature.name if self.signature else ""

    __table_args__ = (
        Index("ix_vaccination_matches_target_created", "target_merchant_id", "matched_at"),
    )
