from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, RoleEnum, get_current_principal, require_role
from app.db.repositories.agent_repo import AgentRepository
from app.db.repositories.reconciliation_repo import (
    TERMINAL_FAILURE_STATUSES,
    TERMINAL_SUCCESS_STATUSES,
    ReconciliationRepository,
)
from app.db.session import get_db
from app.gateway.service import TrustGatewayService, get_gateway_service
from app.models.payout import PayoutRequestRecord
from app.schemas.reconciliation import (
    EscalateRequest,
    ManualReconcileResponse,
    ReconciliationListResponse,
    ReconciliationPayoutSummary,
    ReconciliationStats,
)

router = APIRouter(
    prefix="/reconciliation",
    tags=["Reconciliation (Admin)"],
    dependencies=[Depends(require_role(RoleEnum.ANALYST))],
)


def _payout_summary(payout: PayoutRequestRecord) -> ReconciliationPayoutSummary:
    return ReconciliationPayoutSummary.model_validate(payout)


@router.get(
    "/payouts",
    response_model=ReconciliationListResponse,
    summary="List reconciliation payouts for the authenticated merchant",
    description=(
        "Administrative/analyst view of payouts and their automated reconciliation state. "
        "Scoped to the caller's merchant. No provider credentials or recipient details are returned."
    ),
)
def list_reconciliation_payouts(
    status: str | None = Query(None, description="Filter by payout status"),
    escalated: bool | None = Query(None, description="Filter by escalation state"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> ReconciliationListResponse:
    repo = ReconciliationRepository(db)
    items, total = repo.list_for_merchant(
        principal.merchant_id,
        status=status,
        escalated=escalated,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ReconciliationListResponse(
        items=[_payout_summary(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/stats",
    response_model=ReconciliationStats,
    summary="Reconciliation metrics for the authenticated merchant",
    description="Stuck-payout counts and reconciliation backlog for the analyst console.",
)
def reconciliation_stats(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> ReconciliationStats:
    repo = ReconciliationRepository(db)
    stuck = repo.stuck_count(principal.merchant_id)
    items, total = repo.list_for_merchant(principal.merchant_id, limit=1, offset=0)
    # Count unresolved vs escalated across the merchant (unpaged scan).
    unresolved = 0
    escalated_count = 0
    pending_retry = 0
    now = datetime.now(timezone.utc)
    offset = 0
    while True:
        batch, _ = repo.list_for_merchant(principal.merchant_id, limit=500, offset=offset)
        if not batch:
            break
        for p in batch:
            if p.escalated_at is not None:
                escalated_count += 1
            elif p.status in ("pending", "processing"):
                unresolved += 1
                if p.next_retry_at is not None and p.next_retry_at <= now:
                    pending_retry += 1
        offset += len(batch)
    return ReconciliationStats(
        merchant_id=principal.merchant_id,
        total_unresolved=unresolved,
        total_escalated=escalated_count,
        stuck_payouts=stuck,
        total_pending_retry=pending_retry,
    )


@router.post(
    "/payouts/{payout_id}/reconcile",
    response_model=ManualReconcileResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger an immediate reconciliation for one payout",
    description=(
        "On-demand reconciliation of a single payout against the payment provider. "
        "Uses the existing reconcile_payout() and is idempotent. Merchant-scoped."
    ),
)
def reconcile_one_payout(
    payout_id: UUID = Path(..., description="Payout id to reconcile"),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    gateway_service: TrustGatewayService = Depends(get_gateway_service),
) -> ManualReconcileResponse:
    repo = ReconciliationRepository(db)
    payout = repo.get_by_id(payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    if payout.merchant_id != principal.merchant_id:
        raise HTTPException(status_code=403, detail="Payout belongs to another merchant")

    old_status = payout.status

    # A payout without a provider reference cannot be reconciled; escalate instead.
    if not payout.provider_batch_id:
        repo.mark_escalated(payout, reason="no_provider_reference")
        return ManualReconcileResponse(
            payout_id=payout_id,
            status=payout.status,
            reconciled=False,
            message="Payout has no provider reference and was escalated to manual review.",
        )

    result = gateway_service.reconcile_payout(db, payout_id, principal.merchant_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    db.refresh(payout)
    new_status = payout.status

    if new_status != old_status:
        grant = _find_active_grant(db, payout.session_id, payout.merchant_id)
        if grant:
            agent_repo = AgentRepository(db)
            amount = float(payout.amount)
            if new_status == "completed":
                agent_repo.consume_reservation(grant.grant_id, amount)
            elif new_status in TERMINAL_FAILURE_STATUSES:
                agent_repo.release_reservation(grant.grant_id, amount)

    resolved = new_status in TERMINAL_SUCCESS_STATUSES or new_status in TERMINAL_FAILURE_STATUSES
    repo.record_reconciliation(payout, new_status=new_status, resolved=resolved)

    return ManualReconcileResponse(
        payout_id=payout_id,
        status=new_status,
        reconciled=resolved,
        message=f"Payout reconciled from {old_status} to {new_status}.",
    )


@router.post(
    "/payouts/{payout_id}/escalate",
    response_model=ManualReconcileResponse,
    status_code=status.HTTP_200_OK,
    summary="Manually escalate a payout for analyst review",
    description=(
        "Escalate a payout to manual review, halting all automated retries. "
        "Does not release reservations, resubmit, or delete idempotency records."
    ),
)
def escalate_payout(
    payout_id: UUID = Path(..., description="Payout id to escalate"),
    request: EscalateRequest = EscalateRequest(),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> ManualReconcileResponse:
    repo = ReconciliationRepository(db)
    payout = repo.get_by_id(payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    if payout.merchant_id != principal.merchant_id:
        raise HTTPException(status_code=403, detail="Payout belongs to another merchant")

    repo.mark_escalated(payout, reason=request.reason)
    return ManualReconcileResponse(
        payout_id=payout_id,
        status=payout.status,
        reconciled=False,
        message=f"Payout escalated: {request.reason}.",
    )


def _find_active_grant(db: Session, session_id: UUID, merchant_id: UUID):
    from app.models.agent import AgentAuthorizationGrant

    now = datetime.now(timezone.utc)
    stmt = (
        select(AgentAuthorizationGrant)
        .where(
            AgentAuthorizationGrant.session_id == session_id,
            AgentAuthorizationGrant.merchant_id == merchant_id,
            AgentAuthorizationGrant.revoked_at.is_(None),
            (
                AgentAuthorizationGrant.expires_at.is_(None)
                | (AgentAuthorizationGrant.expires_at > now)
            ),
        )
        .order_by(AgentAuthorizationGrant.issued_at.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()
