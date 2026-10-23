"""
Agentic commerce persistence models (Person 3).

These models describe the *registry* of AI agents that are allowed to act on
behalf of a merchant, the *delegation grants* that authorize a specific agent
to act for a specific merchant user and session, and the append-only audit
trail of agent initiated commerce.

The models deliberately store no payment instrument data and no credentials:
an agent is identified by an opaque id, and its authority always comes from a
server-side grant that is bound to a merchant and a user.
"""

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AgentStatus:
    """Lifecycle states of an agent registration."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class AgentRegistration(Base, TimestampMixin):
    """
    A registered AI agent that may act on behalf of a merchant.

    Registration is a merchant-scoped administrative operation: it records
    WHO the agent is and WHAT it is allowed to do. It never grants authority
    on its own - every action still requires a valid authorization grant.
    """

    __tablename__ = "agent_registrations"

    agent_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("merchants.merchant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_type: Mapped[str] = mapped_column(
        String(64), default="shopping_assistant", nullable=False
    )
    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=AgentStatus.ACTIVE, nullable=False)
    max_payout_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_agent_registrations_merchant_status", "merchant_id", "status"),)


class AgentAuthorizationGrant(Base, TimestampMixin):
    """
    A time-bound delegation from a merchant user to a registered agent.

    The grant is the authorization context of an agent initiated action. It is
    bound to the merchant, the delegating user and (optionally) the session,
    it carries the scopes the agent may exercise, a maximum amount and an
    expiry. A grant is a delegation capability, NOT an authentication
    credential: a caller must additionally present a valid merchant session.
    """

    __tablename__ = "agent_authorization_grants"

    grant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_registrations.agent_id", ondelete="CASCADE"),
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
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    max_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delegated_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_agent_grants_agent_merchant", "agent_id", "merchant_id"),
        Index("ix_agent_grants_expiry", "expires_at"),
    )


class AgenticCommerceAudit(Base, TimestampMixin):
    """
    Append-only audit trail of agent initiated commerce.

    Every attempt that passes authorization (accepted, policy blocked or
    rejected by the gateway) is recorded with the agent identity, the
    authorization context and the resulting payout, so the evidence pipeline
    can attribute an outbound payment to an AI agent. Attempts that fail to
    resolve a registered agent are rejected before this audit is written.
    """

    __tablename__ = "agentic_commerce_audit"

    audit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_registrations.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_authorization_grants.grant_id", ondelete="SET NULL"),
        nullable=True,
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
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payout_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payout_requests.payout_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (Index("ix_agentic_audit_merchant_key", "merchant_id", "idempotency_key"),)
