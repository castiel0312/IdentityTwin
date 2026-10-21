from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, RoleEnum, get_current_principal, require_role
from app.db.session import get_db
from app.schemas.incidents import (
    IncidentActionRequest,
    IncidentActionResponse,
    IncidentListResponse,
    IncidentResponse,
)
from app.services.incident_service import IncidentService

router = APIRouter(prefix="/incidents", tags=["Incident Investigation & Approval"])


@router.get(
    "",
    response_model=IncidentListResponse,
    summary="List security and fraud incidents",
    description="Returns incidents scoped to the merchant domain.",
)
def list_incidents(
    status: str | None = Query(
        None, description="Filter by status (OPEN, UNDER_REVIEW, APPROVED, RESOLVED)"
    ),
    severity: str | None = Query(
        None, description="Filter by severity (LOW, MEDIUM, HIGH, CRITICAL)"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> IncidentListResponse:
    service = IncidentService(db)
    offset = (page - 1) * page_size
    items, total = service.list_incidents(
        principal=principal,
        status=status,
        severity=severity,
        limit=page_size,
        offset=offset,
    )
    return IncidentListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    summary="Get incident details by ID",
)
def get_incident(
    incident_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> IncidentResponse:
    service = IncidentService(db)
    return service.get_incident(incident_id=incident_id, principal=principal)


@router.post(
    "/{incident_id}/approve",
    response_model=IncidentActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve incident review (Analyst Only)",
    description=(
        "Requires analyst credentials. Updates review status and records audit action. "
        "Approval does NOT automatically execute payouts or disable isolation."
    ),
)
def approve_incident(
    incident_id: UUID,
    request: IncidentActionRequest,
    principal: AuthenticatedPrincipal = Depends(require_role(RoleEnum.ANALYST)),
    db: Session = Depends(get_db),
) -> IncidentActionResponse:
    service = IncidentService(db)
    return service.approve_incident(incident_id=incident_id, request=request, principal=principal)


@router.post(
    "/{incident_id}/resolve",
    response_model=IncidentActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve and archive incident (Analyst Only)",
    description="Requires analyst credentials. Resolves incident and logs audit trail.",
)
def resolve_incident(
    incident_id: UUID,
    request: IncidentActionRequest,
    principal: AuthenticatedPrincipal = Depends(require_role(RoleEnum.ANALYST)),
    db: Session = Depends(get_db),
) -> IncidentActionResponse:
    service = IncidentService(db)
    return service.resolve_incident(incident_id=incident_id, request=request, principal=principal)


@router.post(
    "/{incident_id}/approve-revocation",
    response_model=IncidentActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve session revocation for security incident (Analyst/Admin Only)",
    description=(
        "Requires analyst/admin credentials and merchant domain ownership. "
        "Records the audit trail confirming session isolation and permanent revocation. "
        "Guaranteed to never re-enable a session or execute a payout."
    ),
)
def approve_revocation(
    incident_id: UUID,
    request: IncidentActionRequest,
    principal: AuthenticatedPrincipal = Depends(require_role(RoleEnum.ANALYST)),
    db: Session = Depends(get_db),
) -> IncidentActionResponse:
    service = IncidentService(db)
    return service.approve_revocation(incident_id=incident_id, request=request, principal=principal)
