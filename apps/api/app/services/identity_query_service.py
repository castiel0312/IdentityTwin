"""Identity list/detail projections backed by behavioural twins and sessions."""

from datetime import timezone
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import EntityNotFoundException
from app.core.security import AuthenticatedPrincipal
from app.db.repositories.twin_repo import TwinRepository
from app.models.principal import User
from app.models.session import SessionRecord
from app.models.twin import BehavioralTwin
from app.risk.config import get_risk_config
from app.schemas.identities import (
    IdentityDetailResponse,
    IdentityListItem,
    IdentityListResponse,
    TwinSummary,
)
from app.schemas.sessions import SessionResponse, SessionStatus


def _twin_summary(record: BehavioralTwin | None) -> TwinSummary | None:
    if record is None:
        return None
    config = get_risk_config()
    payees = record.payee_observations or {}
    return TwinSummary(
        twin_id=record.twin_id,
        sample_count=record.sample_count,
        is_provisional=record.sample_count < config.min_samples,
        confirmed_device_count=len(record.confirmed_devices or []),
        confirmed_location_count=len(record.confirmed_locations or []),
        confirmed_payee_count=sum(
            1
            for count in payees.values()
            if int(count) >= config.payee_confirm_observations
        ),
        pending_payee_count=sum(
            1
            for count in payees.values()
            if int(count) < config.payee_confirm_observations
        ),
        active_hours=sorted(
            int(hour)
            for hour, count in (record.hour_histogram or {}).items()
            if int(count) > 0
        ),
        amount_count=record.amount_count,
        last_updated_at=record.last_updated_at,
    )


def _session_stats(
    db: Session, merchant_id: UUID, user_ids: list[UUID]
) -> dict[UUID, tuple[int, int, float, object]]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(
            SessionRecord.user_id,
            func.count(SessionRecord.session_id),
            func.sum(
                case(
                    (SessionRecord.status == SessionStatus.ACTIVE.value, 1), else_=0
                )
            ),
            func.max(SessionRecord.risk_score),
            func.max(SessionRecord.last_activity_at),
        )
        .where(
            SessionRecord.merchant_id == merchant_id,
            SessionRecord.user_id.in_(user_ids),
        )
        .group_by(SessionRecord.user_id)
    ).all()
    return {
        row[0]: (int(row[1] or 0), int(row[2] or 0), float(row[3] or 0.0), row[4])
        for row in rows
    }


def _to_item(
    user: User,
    twin: BehavioralTwin | None,
    stats: tuple[int, int, float, object] | None,
) -> IdentityListItem:
    sessions_total, active_sessions, max_risk, last_activity = stats or (0, 0, 0.0, None)
    return IdentityListItem(
        user_id=user.user_id,
        merchant_id=user.merchant_id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        twin=_twin_summary(twin),
        sessions_total=sessions_total,
        active_sessions=active_sessions,
        max_risk_score=max_risk,
        last_activity_at=last_activity if last_activity is None or last_activity.tzinfo else last_activity.replace(tzinfo=timezone.utc),
    )


def list_identities(
    db: Session,
    principal: AuthenticatedPrincipal,
    *,
    q: str | None = None,
    has_twin: bool | None = None,
    page: int = 1,
    page_size: int = 25,
) -> IdentityListResponse:
    filters = [User.merchant_id == principal.merchant_id]
    if q:
        filters.append(
            or_(
                User.email.ilike(f"%{q.strip()}%"),
                User.role.ilike(f"%{q.strip()}%"),
            )
        )
    if has_twin is not None:
        twin_exists = select(BehavioralTwin.twin_id).where(
            BehavioralTwin.merchant_id == principal.merchant_id,
            BehavioralTwin.user_id == User.user_id,
        )
        filters.append(twin_exists.exists() if has_twin else ~twin_exists.exists())

    total = (
        db.scalar(select(func.count()).select_from(User).where(*filters)) or 0
    )
    offset = (page - 1) * page_size
    users = list(
        db.scalars(
            select(User)
            .where(*filters)
            .order_by(User.email.asc())
            .limit(page_size)
            .offset(offset)
        ).all()
    )
    twins = {
        twin.user_id: twin
        for twin in db.scalars(
            select(BehavioralTwin).where(
                BehavioralTwin.merchant_id == principal.merchant_id,
                BehavioralTwin.user_id.in_([user.user_id for user in users]),
            )
        ).all()
    }
    stats = _session_stats(
        db, principal.merchant_id, [user.user_id for user in users]
    )
    return IdentityListResponse(
        items=[_to_item(user, twins.get(user.user_id), stats.get(user.user_id)) for user in users],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_identity_detail(
    db: Session, principal: AuthenticatedPrincipal, user_id: UUID
) -> IdentityDetailResponse:
    user = db.get(User, user_id)
    if user is None or user.merchant_id != principal.merchant_id:
        raise EntityNotFoundException(
            message="Identity not found.", code="IDENTITY_NOT_FOUND"
        )
    twin = TwinRepository(db).get_twin(principal.merchant_id, user_id)
    stats = _session_stats(db, principal.merchant_id, [user_id]).get(user_id)
    sessions = list(
        db.scalars(
            select(SessionRecord)
            .where(
                SessionRecord.merchant_id == principal.merchant_id,
                SessionRecord.user_id == user_id,
            )
            .order_by(SessionRecord.last_activity_at.desc())
            .limit(20)
        ).all()
    )
    limitations = []
    if twin is None:
        limitations.append(
            "No behavioural twin exists yet. Signals remain provisional until "
            f"{settings.RISK_MIN_SAMPLES} baseline observations are collected."
        )
    return IdentityDetailResponse(
        identity=_to_item(user, twin, stats),
        sessions=[SessionResponse.model_validate(session) for session in sessions],
        limitations=limitations,
    )
