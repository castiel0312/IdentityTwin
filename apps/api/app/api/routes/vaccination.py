"""Security Vaccination routes.

Endpoints:
- POST   /v1/vaccination/signatures          extract a PROPOSED signature from a confirmed attack (merchant, own session)
- GET    /v1/vaccination/signatures          list signatures sourced by the merchant
- GET    /v1/vaccination/signatures/{id}     signature detail (source-scoped)
- POST   /v1/vaccination/signatures/{id}/approve   analyst: PROPOSED -> ACTIVE
- POST   /v1/vaccination/signatures/{id}/reject    analyst: PROPOSED -> REVOKED
- POST   /v1/vaccination/signatures/{id}/revoke    analyst: ACTIVE -> REVOKED
- GET    /v1/vaccination/matches             match history (target merchant scoped)
- POST   /v1/vaccination/evaluate            evaluate a session against active signatures

Only ACTIVE signatures are applied during evaluation. The Trust Gateway
remains the final enforcement boundary; a vaccination match adds an explainable
risk signal but never independently authorizes a payment.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.vaccination import (
    VaccinationEvaluateRequest,
    VaccinationEvaluateResponse,
    VaccinationMatchListResponse,
    VaccinationMatchResponse,
    VaccinationSignatureActionRequest,
    VaccinationSignatureActionResponse,
    VaccinationSignatureCreateRequest,
    VaccinationSignatureListResponse,
    VaccinationSignatureResponse,
    VaccinationStatus,
)
from app.services.vaccination_service import VaccinationService

router = APIRouter(prefix="/vaccination", tags=["Security Vaccination"])


def _service(db: Session = Depends(get_db)) -> VaccinationService:
    return VaccinationService(db)


@router.post(
    "/signatures",
    response_model=VaccinationSignatureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Extract a vaccination signature from a confirmed attack",
    description=(
        "Builds a PROPOSED behavioral attack signature from the supplied "
        "session's persisted events. The signature is normalized and sanitized "
        "(no secrets, tokens, or customer PII). It is not applied until an "
        "authorized analyst approves it."
    ),
)
def create_signature(
    request: VaccinationSignatureCreateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    service: VaccinationService = Depends(_service),
    db: Session = Depends(get_db),
) -> VaccinationSignatureResponse:
    session_repo = __import__(
        "app.db.repositories.session_repo", fromlist=["SessionRepository"]
    ).SessionRepository(db)
    session = session_repo.get_by_id(request.session_id)
    if not session:
        from app.core.exceptions import EntityNotFoundException

        raise EntityNotFoundException(
            message=f"Session '{request.session_id}' not found.", code="SESSION_NOT_FOUND"
        )
    signature = service.extract_signature_from_attack(
        session=session, principal=principal, request=request
    )
    return VaccinationSignatureResponse.model_validate(signature)


@router.get(
    "/signatures",
    response_model=VaccinationSignatureListResponse,
    summary="List vaccination signatures sourced by the merchant",
)
def list_signatures(
    status: str | None = Query(
        None, description="Filter by signature status (PROPOSED, ACTIVE, REVOKED)"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    service: VaccinationService = Depends(_service),
) -> VaccinationSignatureListResponse:
    items, total = service.list_signatures(
        principal=principal, status=status, limit=page_size, offset=(page - 1) * page_size
    )
    return VaccinationSignatureListResponse(
        items=[VaccinationSignatureResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/signatures/{signature_id}",
    response_model=VaccinationSignatureResponse,
    summary="Get vaccination signature detail",
)
def get_signature(
    signature_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    service: VaccinationService = Depends(_service),
) -> VaccinationSignatureResponse:
    signature = service.get_signature(signature_id=signature_id, principal=principal)
    return VaccinationSignatureResponse.model_validate(signature)


@router.post(
    "/signatures/{signature_id}/approve",
    response_model=VaccinationSignatureActionResponse,
    summary="Approve a proposed vaccination signature (analyst only)",
    description="Only an ACTIVE signature is applied when evaluating other merchants.",
)
def approve_signature(
    signature_id: UUID,
    request: VaccinationSignatureActionRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    service: VaccinationService = Depends(_service),
) -> VaccinationSignatureActionResponse:
    signature = service.approve_signature(
        signature_id=signature_id, principal=principal, request=request
    )
    return VaccinationSignatureActionResponse(
        signature_id=signature.signature_id,
        action="approve",
        previous_status=VaccinationStatus.PROPOSED,
        new_status=VaccinationStatus(signature.status),
        analyst_id=principal.user_id,
        timestamp=signature.updated_at,
        notes=request.notes,
        message="Signature approved. Only ACTIVE signatures are applied to merchant evaluations.",
    )


@router.post(
    "/signatures/{signature_id}/reject",
    response_model=VaccinationSignatureActionResponse,
    summary="Reject a proposed vaccination signature (analyst only)",
)
def reject_signature(
    signature_id: UUID,
    request: VaccinationSignatureActionRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    service: VaccinationService = Depends(_service),
) -> VaccinationSignatureActionResponse:
    signature = service.reject_signature(
        signature_id=signature_id, principal=principal, request=request
    )
    return VaccinationSignatureActionResponse(
        signature_id=signature.signature_id,
        action="reject",
        previous_status=VaccinationStatus.PROPOSED,
        new_status=VaccinationStatus(signature.status),
        analyst_id=principal.user_id,
        timestamp=signature.updated_at,
        notes=request.notes,
        message="Signature rejected. It will never be applied.",
    )


@router.post(
    "/signatures/{signature_id}/revoke",
    response_model=VaccinationSignatureActionResponse,
    summary="Revoke an active vaccination signature (analyst only)",
)
def revoke_signature(
    signature_id: UUID,
    request: VaccinationSignatureActionRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    service: VaccinationService = Depends(_service),
) -> VaccinationSignatureActionResponse:
    signature = service.revoke_signature(
        signature_id=signature_id, principal=principal, request=request
    )
    return VaccinationSignatureActionResponse(
        signature_id=signature.signature_id,
        action="revoke",
        previous_status=VaccinationStatus.ACTIVE,
        new_status=VaccinationStatus(signature.status),
        analyst_id=principal.user_id,
        timestamp=signature.updated_at,
        notes=request.notes,
        message="Signature revoked. It no longer matches merchant events.",
    )


@router.get(
    "/matches",
    response_model=VaccinationMatchListResponse,
    summary="List vaccination matches recorded for the merchant",
)
def list_matches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    service: VaccinationService = Depends(_service),
) -> VaccinationMatchListResponse:
    items, total = service.list_matches(
        principal=principal, limit=page_size, offset=(page - 1) * page_size
    )
    return VaccinationMatchListResponse(
        items=[VaccinationMatchResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/evaluate",
    response_model=VaccinationEvaluateResponse,
    summary="Evaluate a session against active vaccination signatures",
    description=(
        "Compares the session's observed behavior against active vaccination "
        "signatures. A match adds an explainable risk signal; it does not "
        "independently authorize a payment or bypass the Trust Gateway."
    ),
)
def evaluate_signatures(
    request: VaccinationEvaluateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    service: VaccinationService = Depends(_service),
    db: Session = Depends(get_db),
) -> VaccinationEvaluateResponse:
    session_repo = __import__(
        "app.db.repositories.session_repo", fromlist=["SessionRepository"]
    ).SessionRepository(db)
    session = session_repo.get_by_id(request.session_id)
    if not session:
        from app.core.exceptions import EntityNotFoundException

        raise EntityNotFoundException(
            message=f"Session '{request.session_id}' not found.", code="SESSION_NOT_FOUND"
        )
    detail = service.evaluate(session=session, principal=principal, request=request)
    return VaccinationEvaluateResponse(
        session_id=session.session_id,
        merchant_id=session.merchant_id,
        match=detail,
    )
