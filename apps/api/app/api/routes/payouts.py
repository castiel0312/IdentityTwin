from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.gateway.service import TrustGatewayService, get_gateway_service
from app.schemas.payout_queries import PayoutDetailResponse, PayoutListResponse
from app.schemas.payouts import PayoutRequest, PayoutResponse
from app.services.payout_query_service import get_payout_detail, list_payouts

router = APIRouter(prefix="/payouts", tags=["Protected Payout Operations"])


@router.get(
    "",
    response_model=PayoutListResponse,
    summary="List payouts for the authenticated merchant",
    description=(
        "Read-only projection of payouts already recorded by the Trust Gateway. "
        "It never executes, retries or reconciles a payout."
    ),
)
def list_merchant_payouts(
    q: str | None = Query(
        None, max_length=128, description="Payout id, recipient, reference or idempotency key"
    ),
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Execution status recorded by the gateway",
    ),
    trust_level: str | None = Query(
        None, description="NORMAL, RESTRICTED, DECOY or ISOLATED"
    ),
    provider: str | None = Query(None, description="Provider adapter identity"),
    initiator: str | None = Query(
        None, description="human or agent"
    ),
    start: datetime | None = Query(None, description="Inclusive created-at lower bound"),
    end: datetime | None = Query(None, description="Inclusive created-at upper bound"),
    sort: str = Query(
        "-created_at",
        description="created_at, amount, risk_score or status; prefix with '-' for descending",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> PayoutListResponse:
    return list_payouts(
        db,
        principal,
        q=q,
        status=status_filter,
        trust_level=trust_level,
        provider=provider,
        initiator=initiator,
        start=start,
        end=end,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{payout_id}",
    response_model=PayoutDetailResponse,
    summary="Read one payout and its server-derived execution context",
)
def get_merchant_payout(
    payout_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> PayoutDetailResponse:
    return get_payout_detail(db, principal, payout_id)


@router.post(
    "",
    response_model=PayoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute protected payout through Trust Gateway",
    description=(
        "All payout execution MUST pass through this endpoint and the central Trust Gateway service. "
        "Evaluates real-time risk, applies centralized routing policy, and strictly isolates or rejects "
        "non-eligible trust states."
    ),
)
def execute_payout(
    request: PayoutRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    gateway_service: TrustGatewayService = Depends(get_gateway_service),
) -> PayoutResponse:
    return gateway_service.execute_payout(db=db, request=request, principal=principal)
