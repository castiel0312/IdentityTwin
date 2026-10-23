from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.gateway.agentic import AgenticCommerceService, get_agentic_commerce_service
from app.schemas.agentic import AgenticCommerceRequest, AgenticCommerceResponse

router = APIRouter(prefix="/agentic", tags=["Agentic Commerce"])


@router.post(
    "/payouts",
    response_model=AgenticCommerceResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit an AI agent initiated payout through the Trust Gateway",
    description=(
        "Internal agentic commerce contract (Person 3). The caller states which registered agent is "
        "acting and which delegation authorizes it; the server resolves the agent identity, the "
        "authorization context and the merchant identity, then normalizes the request into the "
        "canonical payout request handled by the Trust Gateway. No payment provider is contacted "
        "from this endpoint and no trust state can be asserted by the caller."
    ),
)
def submit_agentic_payout(
    request: AgenticCommerceRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    agentic_service: AgenticCommerceService = Depends(get_agentic_commerce_service),
) -> AgenticCommerceResponse:
    return agentic_service.submit(db=db, request=request, principal=principal)
