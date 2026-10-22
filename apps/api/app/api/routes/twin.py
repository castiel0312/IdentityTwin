"""Behavioral identity twin viewer API (Person 2).

Exposes the behavioural baseline of an identity and, optionally, the deviation
of a live session from that baseline. The endpoint is strictly merchant scoped.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException, OwnershipMismatchException
from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.repositories.twin_repo import TwinRepository
from app.db.session import get_db
from app.models.principal import User
from app.models.session import SessionRecord
from app.risk.config import get_risk_config
from app.risk.schemas import SessionRiskState, TwinSnapshot
from app.risk.twin import (
    bucket_ip_address,
    confirmed_payees,
    hash_device,
    pending_payees,
)
from app.schemas.sessions import TrustLevel
from app.schemas.twins import TwinDeviationResponse, TwinProfileResponse

router = APIRouter(
    prefix="/identities",
    tags=["Behavioral Identity Twin (Person 2 - Risk Intelligence)"],
)


def _safe_trust_level(value: str | None) -> TrustLevel:
    if not value:
        return TrustLevel.NORMAL
    try:
        return TrustLevel(value.upper())
    except ValueError:
        return TrustLevel.ISOLATED


def _build_deviation(
    db: Session,
    snapshot: TwinSnapshot,
    session_id: UUID,
    principal: AuthenticatedPrincipal,
) -> TwinDeviationResponse:
    session = db.scalars(
        select(SessionRecord).where(SessionRecord.session_id == session_id)
    ).first()
    if session is None:
        raise EntityNotFoundException(
            message=f"Session '{session_id}' not found.",
            code="SESSION_NOT_FOUND",
        )
    if session.merchant_id != principal.merchant_id:
        raise OwnershipMismatchException(
            message="Access denied: Session belongs to another merchant domain.",
            code="SESSION_OWNERSHIP_MISMATCH",
        )

    config = get_risk_config()
    repo = TwinRepository(db)
    record = repo.get_session_state(session_id)
    state = (
        repo.to_state(record)
        if record
        else SessionRiskState(
            session_id=session.session_id,
            merchant_id=session.merchant_id,
            user_id=session.user_id,
        )
    )

    signals: dict[str, float] = {}
    for contribution in state.contributions:
        if contribution.kind == "signal":
            signals[contribution.name] = contribution.points

    device_hash = hash_device(session.device_fingerprint, config.device_hash_salt)
    location_bucket = bucket_ip_address(session.ip_address)

    return TwinDeviationResponse(
        session_id=session.session_id,
        risk_score=float(session.risk_score or 0.0),
        trust_level=_safe_trust_level(session.trust_level),
        risk_signals=signals,
        reason_codes=[c.reason_code for c in state.contributions[-10:]],
        is_new_device=bool(device_hash and device_hash not in snapshot.confirmed_devices),
        is_new_location=bool(
            location_bucket and location_bucket not in snapshot.confirmed_locations
        ),
        session_carried_forward=state.carried_forward,
        raw_points_sum=state.raw_points_sum,
        decay_points=state.decay_points_total,
    )


@router.get(
    "/{id}/twin",
    response_model=TwinProfileResponse,
    summary="Fetch behavioural identity twin profile",
    description=(
        "Returns the behavioural baseline (devices, locations, payees, active hours) "
        "established for one identity inside the authenticated merchant domain."
    ),
)
def get_identity_twin(
    id: UUID,
    compare_session_id: UUID | None = Query(
        None, description="Optional session to compare against the established twin baseline"
    ),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> TwinProfileResponse:
    user = db.scalars(select(User).where(User.user_id == id)).first()
    if user is None:
        raise EntityNotFoundException(
            message=f"Identity '{id}' not found.",
            code="IDENTITY_NOT_FOUND",
        )

    if user.merchant_id != principal.merchant_id:
        raise OwnershipMismatchException(
            message="Access denied: Identity belongs to another merchant domain.",
            code="IDENTITY_OWNERSHIP_MISMATCH",
        )

    repo = TwinRepository(db)
    twin_record = repo.get_twin(principal.merchant_id, id)
    if twin_record is None:
        raise EntityNotFoundException(
            message=f"No behavioural twin has been established for identity '{id}'.",
            code="TWIN_NOT_FOUND",
        )

    config = get_risk_config()
    snapshot = repo.to_snapshot(twin_record)
    confirmed = confirmed_payees(snapshot, config)
    pending = pending_payees(snapshot, config)
    active_hours = sorted(int(hour) for hour, count in snapshot.hour_histogram.items() if count > 0)

    deviation = None
    if compare_session_id is not None:
        deviation = _build_deviation(db, snapshot, compare_session_id, principal)

    return TwinProfileResponse(
        user_id=snapshot.user_id,
        merchant_id=snapshot.merchant_id,
        twin_id=twin_record.twin_id,
        sample_count=snapshot.sample_count,
        is_provisional=snapshot.sample_count < config.min_samples,
        confirmed_device_count=len(snapshot.confirmed_devices),
        confirmed_location_count=len(snapshot.confirmed_locations),
        confirmed_payee_count=len(confirmed),
        pending_payee_count=len(pending),
        active_hours=active_hours,
        hour_histogram={str(k): int(v) for k, v in snapshot.hour_histogram.items()},
        total_amount=snapshot.total_amount,
        amount_count=snapshot.amount_count,
        device_fingerprints=list(snapshot.confirmed_devices),
        location_buckets=list(snapshot.confirmed_locations),
        last_updated_at=snapshot.last_updated_at,
        deviation=deviation,
    )
