from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, RoleEnum, get_current_principal, require_role
from app.db.session import get_db
from app.investigation.service import InvestigationService
from app.schemas.investigations import (
    InvestigationCreateRequest,
    InvestigationListResponse,
    InvestigationResponse,
)

router = APIRouter(tags=["AI Investigator"])


@router.post(
    "/incidents/{incident_id}/investigations",
    response_model=InvestigationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run a read-only AI investigation (Analyst/Admin only)",
    description=(
        "Extracts deterministic, merchant-scoped evidence, applies redaction and "
        "produces an advisory investigation bundle. It never changes risk scores, "
        "trust levels, routing, access or payouts."
    ),
)
def create_investigation(
    incident_id: UUID,
    request: InvestigationCreateRequest | None = None,
    principal: AuthenticatedPrincipal = Depends(require_role(RoleEnum.ANALYST)),
    db: Session = Depends(get_db),
) -> InvestigationResponse:
    return InvestigationService(db).create(
        incident_id=incident_id,
        request=request or InvestigationCreateRequest(),
        principal=principal,
    )


@router.get(
    "/incidents/{incident_id}/investigations",
    response_model=InvestigationListResponse,
    summary="List persisted investigations for an incident",
)
def list_investigations(
    incident_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> InvestigationListResponse:
    return InvestigationService(db).list_for_incident(
        incident_id=incident_id,
        principal=principal,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationResponse,
    summary="Read one persisted investigation",
)
def get_investigation(
    investigation_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> InvestigationResponse:
    return InvestigationService(db).get(investigation_id, principal)
