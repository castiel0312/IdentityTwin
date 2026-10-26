from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.agents import (
    AgentAuditListResponse,
    AgentDetailResponse,
    AgentErrorCatalogResponse,
    AgentListResponse,
)
from app.services.agent_query_service import (
    error_catalog,
    get_agent_detail,
    list_agents,
    list_audit,
)

router = APIRouter(prefix="/agents", tags=["Agentic Commerce Registry"])


@router.get(
    "",
    response_model=AgentListResponse,
    summary="List registered agents for the authenticated merchant",
)
def list_merchant_agents(
    q: str | None = Query(None, max_length=128),
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AgentListResponse:
    return list_agents(
        db, principal, q=q, status=status_filter, page=page, page_size=page_size
    )


@router.get(
    "/audit",
    response_model=AgentAuditListResponse,
    summary="List persisted agent authorization attempts",
    description=(
        "Only attempts that reached the audit recorder are present. Fail-closed "
        "rejections raised before persistence cannot be reconstructed here."
    ),
)
def list_agent_audit(
    agent_id: UUID | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AgentAuditListResponse:
    return list_audit(
        db,
        principal,
        agent_id=agent_id,
        status=status_filter,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/authorization-errors",
    response_model=AgentErrorCatalogResponse,
    summary="Authoritative agent authorization error catalog",
)
def agent_authorization_errors(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> AgentErrorCatalogResponse:
    return error_catalog()


@router.get(
    "/{agent_id}",
    response_model=AgentDetailResponse,
    summary="Read one agent, its grants and recent audit context",
)
def get_merchant_agent(
    agent_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AgentDetailResponse:
    return get_agent_detail(db, principal, agent_id)
