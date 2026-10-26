from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.risk_queries import (
    RiskConfigView,
    RiskDecisionDetailResponse,
    RiskDecisionListResponse,
)
from app.services.risk_query_service import (
    get_decision_detail,
    list_decisions,
    risk_config_view,
)

router = APIRouter(prefix="/risk", tags=["Risk Intelligence"])


@router.get(
    "/config",
    response_model=RiskConfigView,
    summary="Risk thresholds, signal weights and sequence window from the running backend",
)
def get_risk_configuration(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> RiskConfigView:
    return risk_config_view()


@router.get(
    "/decisions",
    response_model=RiskDecisionListResponse,
    summary="List persisted risk decisions",
)
def list_risk_decisions(
    session_id: UUID | None = Query(None),
    trust_level: str | None = Query(None),
    min_score: float | None = Query(None, ge=0.0, le=100.0),
    max_score: float | None = Query(None, ge=0.0, le=100.0),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RiskDecisionListResponse:
    return list_decisions(
        db,
        principal,
        session_id=session_id,
        trust_level=trust_level,
        min_score=min_score,
        max_score=max_score,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/decisions/{decision_id}",
    response_model=RiskDecisionDetailResponse,
    summary="Read one risk decision with its authoritative score snapshot",
)
def get_risk_decision(
    decision_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RiskDecisionDetailResponse:
    return get_decision_detail(db, principal, decision_id)
