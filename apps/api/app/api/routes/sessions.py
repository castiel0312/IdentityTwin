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
    StepUpChallengeCreateResponse,
    StepUpVerifyRequest,
    StepUpVerifyResponse,
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


@router.post(
    "/{session_id}/step-up",
    response_model=StepUpChallengeCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue step-up verification challenge",
    description="Issues a time-bound step-up OTP challenge bound to session and merchant.",
)
def create_step_up_challenge(
    session_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> StepUpChallengeCreateResponse:
    import hashlib
    import secrets
    from datetime import datetime, timedelta, timezone

    from app.core.config import settings
    from app.core.exceptions import PolicyViolationException
    from app.db.repositories.step_up_repo import StepUpRepository
    from app.models.step_up import StepUpChallenge
    from app.schemas.sessions import SessionStatus

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        raise EntityNotFoundException(f"Session '{session_id}' not found.")

    if session.merchant_id != principal.merchant_id or session.user_id != principal.user_id:
        raise OwnershipMismatchException(
            "Access denied: Session does not belong to authenticated principal."
        )

    if session.status != SessionStatus.ACTIVE.value:
        raise PolicyViolationException(
            message=f"Session is in '{session.status}' state and cannot issue step-up challenges.",
            code="INACTIVE_SESSION",
        )

    # Generate 6-digit OTP code
    otp_code = f"{secrets.randbelow(1000000):06d}"
    code_hash = hashlib.sha256(otp_code.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=5)

    challenge = StepUpChallenge(
        session_id=session.session_id,
        merchant_id=principal.merchant_id,
        code_hash=code_hash,
        expires_at=expires_at,
    )
    step_up_repo = StepUpRepository(db)
    saved_challenge = step_up_repo.create(challenge)

    simulated_otp = otp_code if settings.ENVIRONMENT in ("development", "test") else None

    return StepUpChallengeCreateResponse(
        challenge_id=saved_challenge.id,
        session_id=session.session_id,
        expires_at=saved_challenge.expires_at,
        simulated_otp=simulated_otp,
    )


@router.post(
    "/{session_id}/step-up/verify",
    response_model=StepUpVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify step-up challenge OTP code",
    description="Validates step-up challenge code and issues a single-use verification token.",
)
def verify_step_up_challenge(
    session_id: UUID,
    request: StepUpVerifyRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> StepUpVerifyResponse:
    import hashlib
    from datetime import datetime, timezone

    from app.core.exceptions import PolicyViolationException
    from app.db.repositories.step_up_repo import StepUpRepository

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        raise EntityNotFoundException(f"Session '{session_id}' not found.")

    if session.merchant_id != principal.merchant_id or session.user_id != principal.user_id:
        raise OwnershipMismatchException(
            "Access denied: Session does not belong to authenticated principal."
        )

    step_up_repo = StepUpRepository(db)
    challenge = step_up_repo.get_by_id(request.challenge_id)
    if (
        not challenge
        or challenge.session_id != session.session_id
        or challenge.merchant_id != principal.merchant_id
    ):
        raise PolicyViolationException(
            message="Step-up challenge not found or does not belong to this session.",
            code="INVALID_STEP_UP_CHALLENGE",
            status_code=400,
        )

    now = datetime.now(timezone.utc)
    if challenge.used_at is not None:
        raise PolicyViolationException(
            message="Step-up challenge has already been used.",
            code="STEP_UP_CHALLENGE_ALREADY_USED",
            status_code=400,
        )

    challenge_expires_at = challenge.expires_at
    if challenge_expires_at.tzinfo is None:
        challenge_expires_at = challenge_expires_at.replace(tzinfo=timezone.utc)

    if challenge_expires_at < now:
        raise PolicyViolationException(
            message="Step-up challenge has expired.",
            code="STEP_UP_CHALLENGE_EXPIRED",
            status_code=400,
        )

    candidate_hash = hashlib.sha256(request.code.strip().encode()).hexdigest()
    if candidate_hash != challenge.code_hash:
        raise PolicyViolationException(
            message="Invalid step-up OTP code provided.",
            code="INVALID_STEP_UP_CODE",
            status_code=400,
        )

    step_up_repo.mark_verified(challenge)

    return StepUpVerifyResponse(
        challenge_id=challenge.id,
        session_id=session.session_id,
        status="verified",
        step_up_token=str(challenge.id),
        expires_at=challenge.expires_at,
    )
