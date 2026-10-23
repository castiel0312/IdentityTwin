from datetime import datetime
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

    def save_grant(self, grant: AgentAuthorizationGrant) -> AgentAuthorizationGrant:
        self.db.add(grant)
        self.db.commit()
        self.db.refresh(grant)
        return grant

    def mark_grant_consumed(self, grant: AgentAuthorizationGrant, consumed_at: datetime) -> None:
        grant.consumed_at = consumed_at
        self.db.commit()

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
