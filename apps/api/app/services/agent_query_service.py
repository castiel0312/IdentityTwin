"""Agent registry, grant and audit read projections."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException
from app.core.security import AuthenticatedPrincipal
from app.models.agent import (
    AgentAuthorizationGrant,
    AgenticCommerceAudit,
    AgentRegistration,
)
from app.schemas.agents import (
    AgentAuditItem,
    AgentAuditListResponse,
    AgentDetailResponse,
    AgentErrorCatalogResponse,
    AgentErrorDefinition,
    AgentGrantView,
    AgentListItem,
    AgentListResponse,
)
from app.services.payout_query_service import payout_items_for_ids

AUTHORIZATION_ERRORS = [
    AgentErrorDefinition(
        code="AGENT_NOT_REGISTERED",
        http_status=403,
        title="Agent not registered",
        explanation="The supplied agent_id is not present in the server-side agent registry.",
        remediation="Register the agent administratively; the caller cannot self-describe.",
    ),
    AgentErrorDefinition(
        code="AGENT_MERCHANT_MISMATCH",
        http_status=403,
        title="Agent belongs to another merchant",
        explanation="The registered agent is scoped to a different merchant domain.",
        remediation="Use an agent registered to the authenticated merchant.",
    ),
    AgentErrorDefinition(
        code="AGENT_NOT_ACTIVE",
        http_status=403,
        title="Agent is not active",
        explanation="The agent registration is suspended, revoked or otherwise inactive.",
        remediation="Reactivate the registration administratively before retrying.",
    ),
    AgentErrorDefinition(
        code="AGENT_AUTHORIZATION_MISSING",
        http_status=403,
        title="Authorization grant missing",
        explanation="No delegation grant exists for the supplied authorization_grant_id.",
        remediation="Present a valid grant issued to this agent for this merchant user.",
    ),
    AgentErrorDefinition(
        code="AGENT_AUTHORIZATION_AGENT_MISMATCH",
        http_status=403,
        title="Grant issued to another agent",
        explanation="The delegation grant was not issued to the agent named in the request.",
        remediation="Use the grant that belongs to the acting agent.",
    ),
    AgentErrorDefinition(
        code="AGENT_AUTHORIZATION_MERCHANT_MISMATCH",
        http_status=403,
        title="Grant merchant mismatch",
        explanation="The delegation grant is scoped to a different merchant.",
        remediation="Use a grant issued inside the authenticated merchant scope.",
    ),
    AgentErrorDefinition(
        code="AGENT_AUTHORIZATION_PRINCIPAL_MISMATCH",
        http_status=403,
        title="Grant principal mismatch",
        explanation="The delegation grant was issued to a different merchant user.",
        remediation="The authenticated user must be the delegating principal.",
    ),
    AgentErrorDefinition(
        code="AGENT_AUTHORIZATION_REVOKED",
        http_status=403,
        title="Grant revoked",
        explanation="The delegation grant has been explicitly revoked.",
        remediation="Issue a new grant; revoked grants cannot be replayed.",
    ),
    AgentErrorDefinition(
        code="AGENT_AUTHORIZATION_CONSUMED",
        http_status=403,
        title="Grant already consumed",
        explanation="The delegation grant is single-use and has already been consumed.",
        remediation="Issue a new grant for a new authorization.",
    ),
    AgentErrorDefinition(
        code="AGENT_AUTHORIZATION_EXPIRED",
        http_status=403,
        title="Grant expired",
        explanation="The delegation grant is outside its validity window.",
        remediation="Issue a fresh time-bound grant.",
    ),
    AgentErrorDefinition(
        code="AGENT_AUTHORIZATION_SESSION_MISMATCH",
        http_status=403,
        title="Grant session mismatch",
        explanation="The grant is bound to a different session than the one presented.",
        remediation="Present the session the delegation was bound to, or issue a new grant.",
    ),
    AgentErrorDefinition(
        code="AGENT_SCOPE_NOT_GRANTED",
        http_status=403,
        title="Required scope not granted",
        explanation="The agent and grant do not both hold the payout:execute scope.",
        remediation="Grant payout:execute on both the registration and the delegation.",
    ),
    AgentErrorDefinition(
        code="AGENT_AMOUNT_LIMIT_EXCEEDED",
        http_status=403,
        title="Amount limit exceeded",
        explanation="The requested amount exceeds the effective agent or grant ceiling.",
        remediation="Reduce the amount or issue a grant with a sufficient ceiling.",
    ),
    AgentErrorDefinition(
        code="AGENT_IDEMPOTENCY_KEY_CONFLICT",
        http_status=409,
        title="Idempotency key conflict",
        explanation=(
            "The idempotency key is already bound to a different execution context "
            "(another agent or a direct payout)."
        ),
        remediation="Use a fresh idempotency key for a genuinely new payment.",
    ),
]


def _grant_status(grant: AgentAuthorizationGrant, now: datetime) -> str:
    if grant.revoked_at is not None:
        return "revoked"
    if grant.consumed_at is not None:
        return "consumed"
    expires = grant.expires_at if grant.expires_at.tzinfo else grant.expires_at.replace(tzinfo=timezone.utc)
    if expires <= now:
        return "expired"
    return "active"


def _grant_view(grant: AgentAuthorizationGrant, now: datetime) -> AgentGrantView:
    return AgentGrantView(
        grant_id=grant.grant_id,
        agent_id=grant.agent_id,
        merchant_id=grant.merchant_id,
        user_id=grant.user_id,
        session_id=grant.session_id,
        scopes=list(grant.scopes or []),
        max_amount=grant.max_amount,
        issued_at=grant.issued_at,
        expires_at=grant.expires_at,
        consumed_at=grant.consumed_at,
        revoked_at=grant.revoked_at,
        status=_grant_status(grant, now),
    )


def _audit_view(
    audit: AgenticCommerceAudit, agent: AgentRegistration | None
) -> AgentAuditItem:
    return AgentAuditItem(
        audit_id=audit.audit_id,
        agent_id=audit.agent_id,
        agent_display_name=agent.display_name if agent else None,
        grant_id=audit.grant_id,
        session_id=audit.session_id,
        payout_id=audit.payout_id,
        idempotency_key=audit.idempotency_key,
        recipient_email=audit.recipient_email,
        amount=audit.amount,
        currency=audit.currency,
        status=audit.status,
        outcome=audit.outcome,
        agent_context=dict(audit.agent_context or {}),
        created_at=audit.created_at,
    )


def list_agents(
    db: Session,
    principal: AuthenticatedPrincipal,
    *,
    q: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> AgentListResponse:
    filters = [AgentRegistration.merchant_id == principal.merchant_id]
    if q:
        filters.append(AgentRegistration.display_name.ilike(f"%{q.strip()}%"))
    if status:
        filters.append(AgentRegistration.status == status.strip().lower())

    total = (
        db.scalar(select(func.count()).select_from(AgentRegistration).where(*filters))
        or 0
    )
    offset = (page - 1) * page_size
    agents = list(
        db.scalars(
            select(AgentRegistration)
            .where(*filters)
            .order_by(AgentRegistration.display_name.asc())
            .limit(page_size)
            .offset(offset)
        ).all()
    )
    agent_ids = [agent.agent_id for agent in agents]
    now = datetime.now(timezone.utc)

    grants = list(
        db.scalars(
            select(AgentAuthorizationGrant).where(
                AgentAuthorizationGrant.merchant_id == principal.merchant_id,
                AgentAuthorizationGrant.agent_id.in_(agent_ids),
            )
        ).all()
    )
    grant_counts: dict[UUID, tuple[int, int]] = {}
    for grant in grants:
        total_grants, active = grant_counts.get(grant.agent_id, (0, 0))
        grant_counts[grant.agent_id] = (
            total_grants + 1,
            active + (1 if _grant_status(grant, now) == "active" else 0),
        )

    audit_rows = db.execute(
        select(
            AgenticCommerceAudit.agent_id,
            func.count(AgenticCommerceAudit.audit_id),
            func.max(AgenticCommerceAudit.created_at),
        )
        .where(
            AgenticCommerceAudit.merchant_id == principal.merchant_id,
            AgenticCommerceAudit.agent_id.in_(agent_ids),
        )
        .group_by(AgenticCommerceAudit.agent_id)
    ).all()
    audit_stats = {
        row[0]: (int(row[1] or 0), row[2]) for row in audit_rows
    }

    items = []
    for agent in agents:
        total_grants, active_grants = grant_counts.get(agent.agent_id, (0, 0))
        attempts, last_activity = audit_stats.get(agent.agent_id, (0, None))
        items.append(
            AgentListItem(
                agent_id=agent.agent_id,
                merchant_id=agent.merchant_id,
                display_name=agent.display_name,
                agent_type=agent.agent_type,
                vendor=agent.vendor,
                scopes=list(agent.scopes or []),
                status=agent.status,
                is_active=agent.is_active,
                max_payout_amount=agent.max_payout_amount,
                description=agent.description,
                active_grants=active_grants,
                total_grants=total_grants,
                audit_attempts=attempts,
                last_activity_at=last_activity,
            )
        )
    return AgentListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


def get_agent_detail(
    db: Session, principal: AuthenticatedPrincipal, agent_id: UUID
) -> AgentDetailResponse:
    listed = list_agents(db, principal, page=1, page_size=1000)
    item = next((agent for agent in listed.items if agent.agent_id == agent_id), None)
    if item is None:
        raise EntityNotFoundException(
            message="Agent not found.", code="AGENT_NOT_FOUND"
        )
    now = datetime.now(timezone.utc)
    grants = list(
        db.scalars(
            select(AgentAuthorizationGrant)
            .where(
                AgentAuthorizationGrant.merchant_id == principal.merchant_id,
                AgentAuthorizationGrant.agent_id == agent_id,
            )
            .order_by(AgentAuthorizationGrant.issued_at.desc())
        ).all()
    )
    audit_rows = db.execute(
        select(AgenticCommerceAudit)
        .where(
            AgenticCommerceAudit.merchant_id == principal.merchant_id,
            AgenticCommerceAudit.agent_id == agent_id,
        )
        .order_by(AgenticCommerceAudit.created_at.desc())
        .limit(50)
    ).scalars().all()
    payout_ids = [row.payout_id for row in audit_rows if row.payout_id is not None]
    return AgentDetailResponse(
        agent=item,
        grants=[_grant_view(grant, now) for grant in grants],
        recent_audit=[
            _audit_view(row, None)
            for row in audit_rows[:20]
        ],
        recent_payouts=payout_items_for_ids(db, principal.merchant_id, payout_ids[:20]),
    )


def list_audit(
    db: Session,
    principal: AuthenticatedPrincipal,
    *,
    agent_id: UUID | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> AgentAuditListResponse:
    filters = [AgenticCommerceAudit.merchant_id == principal.merchant_id]
    if agent_id:
        filters.append(AgenticCommerceAudit.agent_id == agent_id)
    if status:
        filters.append(AgenticCommerceAudit.status == status.strip().lower())

    total = (
        db.scalar(
            select(func.count())
            .select_from(AgenticCommerceAudit)
            .where(*filters)
        )
        or 0
    )
    offset = (page - 1) * page_size
    rows = db.execute(
        select(AgenticCommerceAudit, AgentRegistration)
        .outerjoin(
            AgentRegistration,
            AgentRegistration.agent_id == AgenticCommerceAudit.agent_id,
        )
        .where(*filters)
        .order_by(AgenticCommerceAudit.created_at.desc())
        .limit(page_size)
        .offset(offset)
    ).all()
    return AgentAuditListResponse(
        items=[_audit_view(audit, agent) for audit, agent in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def error_catalog() -> AgentErrorCatalogResponse:
    return AgentErrorCatalogResponse(errors=AUTHORIZATION_ERRORS)
