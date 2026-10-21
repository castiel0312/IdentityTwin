from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException, OwnershipMismatchException
from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.repositories.session_repo import SessionRepository
from app.db.session import get_db
from app.models.session import SessionRecord
from app.schemas.sessions import (
    SessionCreateRequest,
    SessionListResponse,
    SessionResponse,
    TrustLevel,
)

router = APIRouter(prefix="/sessions", tags=["Session Trust Management"])


@router.get(
    "",
    response_model=SessionListResponse,
    summary="List active sessions for merchant domain",
)
def list_sessions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> SessionListResponse:
    repo = SessionRepository(db)
    offset = (page - 1) * page_size
    items, total = repo.list_by_merchant(principal.merchant_id, limit=page_size, offset=offset)
    return SessionListResponse(
        items=[SessionResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get session trust state by ID",
)
def get_session(
    session_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> SessionResponse:
    repo = SessionRepository(db)
    session = repo.get_by_id(session_id)
    if not session:
        raise EntityNotFoundException(f"Session '{session_id}' not found.")

    if session.merchant_id != principal.merchant_id:
        raise OwnershipMismatchException(
            "Access denied: Session belongs to another merchant domain."
        )

    return SessionResponse.model_validate(session)


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user session",
    description="Initializes a new session bound to authenticated principal with baseline NORMAL trust level.",
)
def create_session(
    request: SessionCreateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> SessionResponse:
    repo = SessionRepository(db)
    new_session = SessionRecord(
        user_id=principal.user_id,
        merchant_id=principal.merchant_id,
        trust_level=TrustLevel.NORMAL.value,
        risk_score=0.0,
        status="active",
        device_fingerprint=request.device_fingerprint,
        ip_address=request.ip_address,
    )
    saved = repo.create(new_session)
    return SessionResponse.model_validate(saved)
