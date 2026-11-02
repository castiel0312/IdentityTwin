from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.security import (
    AuthenticatedPrincipal,
    RoleEnum,
    get_current_principal,
    require_role,
)
from app.db.session import get_db
from app.intent.service import IntentProfileService
from app.schemas.intent import (
    IntentProfileCreateRequest,
    IntentProfileListResponse,
    IntentProfileResponse,
)

router = APIRouter(tags=["Intent Profiler"])


@router.post(
    "/sessions/{session_id}/intent-profiles",
    response_model=IntentProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an advisory intent profile (Analyst/Admin only)",
    description=(
        "Builds and persists a bounded, merchant-scoped intent hypothesis from "
        "derived session evidence. The result is advisory only and never changes "
        "risk scores, trust levels, routing, access or payouts."
    ),
)
def create_intent_profile(
    session_id: UUID,
    request: IntentProfileCreateRequest | None = None,
    principal: AuthenticatedPrincipal = Depends(require_role(RoleEnum.ANALYST)),
    db: Session = Depends(get_db),
) -> IntentProfileResponse:
    return IntentProfileService(db).create(
        session_id=session_id,
        request=request or IntentProfileCreateRequest(),
        principal=principal,
    )


@router.get(
    "/sessions/{session_id}/intent-profiles",
    response_model=IntentProfileListResponse,
    summary="List persisted intent profiles for a session",
)
def list_intent_profiles(
    session_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> IntentProfileListResponse:
    return IntentProfileService(db).list_for_session(
        session_id=session_id,
        principal=principal,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/intent-profiles/{profile_id}",
    response_model=IntentProfileResponse,
    summary="Read one persisted advisory intent profile",
)
def get_intent_profile(
    profile_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> IntentProfileResponse:
    return IntentProfileService(db).get(profile_id, principal)
