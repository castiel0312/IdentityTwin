from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.gateway.service import TrustGatewayService, get_gateway_service
from app.schemas.payouts import PayoutRequest, PayoutResponse

router = APIRouter(prefix="/payouts", tags=["Protected Payout Operations"])


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
