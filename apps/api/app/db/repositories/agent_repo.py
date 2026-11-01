from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import (
    AgentAuthorizationGrant,
    AgenticCommerceAudit,
    AgentRegistration,
)


class AgentRepository:
    """Repository for the agent registry, delegation grants and audit trail."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def get_agent(self, agent_id: UUID) -> AgentRegistration | None:
        stmt = select(AgentRegistration).where(AgentRegistration.agent_id == agent_id)
        return self.db.scalars(stmt).first()

    def list_agents_for_merchant(self, merchant_id: UUID) -> list[AgentRegistration]:
        stmt = select(AgentRegistration).where(AgentRegistration.merchant_id == merchant_id)
        return list(self.db.scalars(stmt).all())

    def save_agent(self, agent: AgentRegistration) -> AgentRegistration:
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    # ------------------------------------------------------------------
    # Authorization grants
    # ------------------------------------------------------------------
    def get_grant(self, grant_id: UUID) -> AgentAuthorizationGrant | None:
        stmt = select(AgentAuthorizationGrant).where(AgentAuthorizationGrant.grant_id == grant_id)
        return self.db.scalars(stmt).first()

    def get_grant_for_update(self, grant_id: UUID) -> AgentAuthorizationGrant | None:
        """
        Load a grant with a row-level lock for concurrent spending enforcement.

        Uses ``SELECT ... FOR UPDATE`` so that concurrent payout requests
        against the same grant are serialized at the database level. Only one
        request can hold the lock at a time, preventing two $60 payouts from
        both being accepted against a $100 grant.
        """
        stmt = (
            select(AgentAuthorizationGrant)
            .where(AgentAuthorizationGrant.grant_id == grant_id)
            .with_for_update()
        )
        return self.db.scalars(stmt).first()

    def save_grant(self, grant: AgentAuthorizationGrant) -> AgentAuthorizationGrant:
        self.db.add(grant)
        self.db.commit()
        self.db.refresh(grant)
        return grant

    def mark_grant_consumed(self, grant: AgentAuthorizationGrant, consumed_at: datetime) -> None:
        """
        Mark a grant as consumed (single-use delegation exhausted).

        This records the consumed timestamp but does NOT itself enforce
        cumulative financial limits: callers must separately verify remaining
        budget via ``reserve_spending_capacity`` before any provider call.
        """
        grant.consumed_at = consumed_at
        self.db.commit()

    def reserve_spending_capacity(
        self, grant_id: UUID, amount: float
    ) -> AgentAuthorizationGrant | None:
        """
        Atomically reserve spending capacity against a grant.

        Returns the grant with the reservation applied, or None if the grant
        does not exist or has insufficient remaining capacity.

        Remaining capacity is calculated as:
            max_amount - total_consumed_amount - reserved_amount

        The reservation is held in ``reserved_amount`` until either:
        - ``consume_reservation`` moves it to ``total_consumed_amount`` (provider success), or
        - ``release_reservation`` returns it to available capacity (definitive provider failure).

        Ambiguous outcomes (timeouts) deliberately do NOT release the
        reservation: the grant stays locked until reconciliation.
        """
        grant = self.get_grant_for_update(grant_id)
        if grant is None:
            return None

        # Reject revoked or expired grants immediately
        if grant.revoked_at is not None:
            return None
        if grant.expires_at is not None:
            expires_at = grant.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                return None

        # Calculate remaining capacity
        max_amount = grant.max_amount
        if max_amount is not None:
            already_used = grant.total_consumed_amount + grant.reserved_amount
            remaining = max_amount - already_used
            if remaining < amount:
                return None

        # Atomically reserve the amount
        grant.reserved_amount = grant.reserved_amount + amount
        self.db.add(grant)
        self.db.flush()
        self.db.refresh(grant)
        return grant

    def consume_reservation(
        self, grant_id: UUID, amount: float
    ) -> AgentAuthorizationGrant | None:
        """
        Move a reserved amount into total consumed (provider confirmed success).

        This permanently debits the grant. The amount must have been previously
        reserved via ``reserve_spending_capacity``.
        """
        grant = self.get_grant_for_update(grant_id)
        if grant is None:
            return None

        grant.reserved_amount = max(0.0, grant.reserved_amount - amount)
        grant.total_consumed_amount = grant.total_consumed_amount + amount
        self.db.add(grant)
        self.db.flush()
        self.db.refresh(grant)
        return grant

    def release_reservation(
        self, grant_id: UUID, amount: float
    ) -> AgentAuthorizationGrant | None:
        """
        Release a reserved amount back to available capacity (definitive provider failure).

        Called only when the provider definitively reports failure (rejection,
        rate limit, explicit unsuccessful result). Ambiguous timeouts must NOT
        call this: they keep the reservation until reconciliation.
        """
        grant = self.get_grant_for_update(grant_id)
        if grant is None:
            return None

        grant.reserved_amount = max(0.0, grant.reserved_amount - amount)
        self.db.add(grant)
        self.db.flush()
        self.db.refresh(grant)
        return grant

    def get_spending_summary(self, grant_id: UUID) -> dict | None:
        """
        Return the current spending state of a grant.

        Includes max_amount, total_consumed_amount, reserved_amount and
        remaining capacity.
        """
        grant = self.get_grant(grant_id)
        if grant is None:
            return None
        max_amount = grant.max_amount or 0.0
        remaining = max_amount - grant.total_consumed_amount - grant.reserved_amount
        return {
            "grant_id": str(grant_id),
            "max_amount": max_amount,
            "total_consumed_amount": grant.total_consumed_amount,
            "reserved_amount": grant.reserved_amount,
            "remaining_amount": max(0.0, remaining),
            "revoked_at": grant.revoked_at,
            "expires_at": grant.expires_at,
        }

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------
    def record_audit(self, audit: AgenticCommerceAudit) -> AgenticCommerceAudit:
        self.db.add(audit)
        self.db.commit()
        self.db.refresh(audit)
        return audit

    def latest_audit_for_key(
        self, merchant_id: UUID, idempotency_key: str
    ) -> AgenticCommerceAudit | None:
        """
        Return the most recent agentic attempt for an idempotency key.

        Used to detect a key that is already bound to a different execution
        context (another agent, or a direct human payout), which must never be
        replayed through the agentic path.
        """
        stmt = (
            select(AgenticCommerceAudit)
            .where(
                AgenticCommerceAudit.merchant_id == merchant_id,
                AgenticCommerceAudit.idempotency_key == idempotency_key,
            )
            .order_by(AgenticCommerceAudit.created_at.desc())
        )
        return self.db.scalars(stmt).first()

    def list_audit_for_agent(self, agent_id: UUID) -> list[AgenticCommerceAudit]:
        stmt = select(AgenticCommerceAudit).where(AgenticCommerceAudit.agent_id == agent_id)
        return list(self.db.scalars(stmt).all())
