import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.models.base import Base, utc_now


class EvidenceLogEntry(Base):
    __tablename__ = "evidence_log"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    merchant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        Index("ix_evidence_log_scope_seq", "session_id", "merchant_id", "seq"),
    )


class EvidencePayload(Base):
    __tablename__ = "evidence_payload"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    payload: Mapped[dict[str, Any]] = mapped_column(__import__("sqlalchemy").JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class EvidenceChainHead(Base):
    __tablename__ = "evidence_chain_head"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)


class HoneyWorkspaceState(Base):
    __tablename__ = "workspace_state"
    __table_args__ = {"schema": "honey"}

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    identity_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    world: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class HoneyScopedRecord:
    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    identity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    @declared_attr
    def __table_args__(cls):
        return (
            Index(f"ix_{cls.__tablename__}_identity_id", "identity_id"),
            {"schema": "honey"},
        )


class HoneyMerchantProfile(HoneyScopedRecord, Base):
    __tablename__ = "merchant_profile"


class HoneyBalance(HoneyScopedRecord, Base):
    __tablename__ = "balances"


class HoneyCustomer(HoneyScopedRecord, Base):
    __tablename__ = "customers"


class HoneyInvoice(HoneyScopedRecord, Base):
    __tablename__ = "invoices"


class HoneyTransaction(HoneyScopedRecord, Base):
    __tablename__ = "transactions"


class HoneyPayout(HoneyScopedRecord, Base):
    __tablename__ = "payouts"


class HoneyPayee(HoneyScopedRecord, Base):
    __tablename__ = "payees"


class HoneyApiCredential(HoneyScopedRecord, Base):
    __tablename__ = "api_credentials"


class HoneyActivityLog(HoneyScopedRecord, Base):
    __tablename__ = "activity_log"


class IncidentSeal(Base):
    __tablename__ = "incident_seals"

    seal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    merchant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    start_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    head_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    sealed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
