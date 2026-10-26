from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.system import SystemContextResponse
from app.services.system_service import build_system_context

router = APIRouter(prefix="/system", tags=["System & Access"])


@router.get(
    "/context",
    response_model=SystemContextResponse,
    summary="Safe system, authentication, provider and risk configuration context",
    description=(
        "Projects non-secret configuration facts for the operator console. "
        "Credentials, bearer tokens and provider secrets are never returned."
    ),
)
def system_context(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> SystemContextResponse:
    return build_system_context(db, principal)
