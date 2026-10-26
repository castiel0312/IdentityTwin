from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db, get_honey_db
from app.schemas.honey_operator import (
    HoneyCanaryListResponse,
    HoneyWorkspaceDetailResponse,
    HoneyWorkspaceListResponse,
)
from app.services.honey_operator_service import (
    get_workspace,
    list_canaries,
    list_workspaces,
)

router = APIRouter(prefix="/honey/operator", tags=["Honey Workspace (Operator Read-Only)"])


@router.get(
    "/workspaces",
    response_model=HoneyWorkspaceListResponse,
    summary="List synthetic honey workspaces for the authenticated merchant",
    description=(
        "Read-only operator projection. It never touches the attacker-facing honey "
        "routes, never returns canary secret values and never executes a synthetic payout."
    ),
)
def list_honey_workspaces(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
) -> HoneyWorkspaceListResponse:
    return list_workspaces(db, honey_db, principal, page=page, page_size=page_size)


@router.get(
    "/canaries",
    response_model=HoneyCanaryListResponse,
    summary="List canary inventory metadata without secret values",
)
def list_honey_canaries(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> HoneyCanaryListResponse:
    return list_canaries(db, principal)


@router.get(
    "/workspaces/{session_id}",
    response_model=HoneyWorkspaceDetailResponse,
    summary="Read one synthetic honey workspace",
)
def get_honey_workspace(
    session_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
) -> HoneyWorkspaceDetailResponse:
    return get_workspace(db, honey_db, principal, session_id)
