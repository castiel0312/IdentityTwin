"""Risk decision read projections for the Risk Intelligence console."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import EntityNotFoundException
from app.core.security import AuthenticatedPrincipal
from app.db.repositories.twin_repo import TwinRepository
from app.models.payout import PayoutRequestRecord
from app.models.risk import RiskDecisionRecord
from app.models.session import SessionRecord
from app.risk.config import get_risk_config
from app.risk.schemas import RiskContribution, SequenceMarker
from app.schemas.risk_queries import (
    RiskConfigView,
    RiskDecisionDetailResponse,
    RiskDecisionItem,
    RiskDecisionListResponse,
    RiskSignalDefinition,
    RiskTwinComparison,
)
from app.schemas.sessions import SessionResponse
from app.services.payout_query_service import configured_signal_weights, payout_items_for_ids
from app.services.system_service import SIGNAL_DESCRIPTIONS


def _decision_item(
    decision: RiskDecisionRecord, payout_id: UUID | None
) -> RiskDecisionItem:
    return RiskDecisionItem(
        decision_id=decision.decision_id,
        session_id=decision.session_id,
        payout_id=payout_id,
        risk_score=decision.risk_score,
        trust_level=decision.trust_level,
        action=decision.action,
        routing_destination=decision.routing_destination,
        reason_codes=list(decision.reason_codes or []),
        risk_signals=dict(decision.risk_signals or {}),
        evaluated_at=decision.evaluated_at,
    )


def _signal_definitions() -> list[RiskSignalDefinition]:
    weights = configured_signal_weights()
    return [
        RiskSignalDefinition(
            name=name,
            weight=weight,
            description=SIGNAL_DESCRIPTIONS.get(name, "Configured risk signal."),
        )
        for name, weight in weights.items()
    ]


def risk_config_view() -> RiskConfigView:
    config = get_risk_config()
    return RiskConfigView(
        thresholds={
            "restricted": config.threshold_restricted,
            "decoy": config.threshold_decoy,
            "isolated": config.threshold_isolated,
            "restricted_payout_limit": settings.RESTRICTED_PAYOUT_LIMIT,
        },
        signals=_signal_definitions(),
        sequence_window_seconds=config.sequence_window_seconds,
        min_samples=config.min_samples,
        provisional_factor=config.provisional_factor,
        decay_points_per_event=config.decay_points_per_event,
        default_timezone=config.default_timezone,
        protected_actions=sorted(config.protected_actions),
    )


def list_decisions(
    db: Session,
    principal: AuthenticatedPrincipal,
    *,
    session_id: UUID | None = None,
    trust_level: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    page_size: int = 25,
) -> RiskDecisionListResponse:
    filters = [RiskDecisionRecord.merchant_id == principal.merchant_id]
    if session_id:
        filters.append(RiskDecisionRecord.session_id == session_id)
    if trust_level:
        filters.append(RiskDecisionRecord.trust_level == trust_level.strip().upper())
    if min_score is not None:
        filters.append(RiskDecisionRecord.risk_score >= min_score)
    if max_score is not None:
        filters.append(RiskDecisionRecord.risk_score <= max_score)
    if start:
        filters.append(RiskDecisionRecord.evaluated_at >= start)
    if end:
        filters.append(RiskDecisionRecord.evaluated_at <= end)

    total = (
        db.scalar(
            select(func.count())
            .select_from(RiskDecisionRecord)
            .where(*filters)
        )
        or 0
    )
    offset = (page - 1) * page_size
    rows = db.execute(
        select(RiskDecisionRecord, PayoutRequestRecord.payout_id)
        .outerjoin(
            PayoutRequestRecord,
            PayoutRequestRecord.decision_id == RiskDecisionRecord.decision_id,
        )
        .where(*filters)
        .order_by(RiskDecisionRecord.evaluated_at.desc())
        .limit(page_size)
        .offset(offset)
    ).all()
    return RiskDecisionListResponse(
        items=[_decision_item(decision, payout_id) for decision, payout_id in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_decision_detail(
    db: Session, principal: AuthenticatedPrincipal, decision_id: UUID
) -> RiskDecisionDetailResponse:
    decision = db.get(RiskDecisionRecord, decision_id)
    if decision is None or decision.merchant_id != principal.merchant_id:
        raise EntityNotFoundException(
            message="Risk decision not found.", code="RISK_DECISION_NOT_FOUND"
        )
    session = db.get(SessionRecord, decision.session_id)
    if session is None:
        raise EntityNotFoundException(
            message="Session for this decision is unavailable.",
            code="SESSION_NOT_FOUND",
        )
    payout = db.scalars(
        select(PayoutRequestRecord).where(
            PayoutRequestRecord.decision_id == decision.decision_id
        )
    ).first()
    payouts = (
        payout_items_for_ids(db, principal.merchant_id, [payout.payout_id])
        if payout is not None
        else []
    )

    contributions: list[RiskContribution] = []
    sequence_markers: list[SequenceMarker] = []
    record = TwinRepository(db).get_session_state(session.session_id)
    if record is not None:
        state = TwinRepository(db).to_state(record)
        contributions = list(state.contributions)
        sequence_markers = list(state.sequence_markers)

    twin_record = TwinRepository(db).get_twin(principal.merchant_id, session.user_id)
    twin = None
    if twin_record is not None:
        config = get_risk_config()
        payees = twin_record.payee_observations or {}
        twin = RiskTwinComparison(
            is_provisional=twin_record.sample_count < config.min_samples,
            sample_count=twin_record.sample_count,
            confirmed_device_count=len(twin_record.confirmed_devices or []),
            confirmed_location_count=len(twin_record.confirmed_locations or []),
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
        )

    return RiskDecisionDetailResponse(
        decision=_decision_item(decision, payout.payout_id if payout else None),
        session=SessionResponse.model_validate(session),
        payout=payouts[0] if payouts else None,
        signals=_signal_definitions(),
        contributions=contributions,
        sequence_markers=sequence_markers,
        twin=twin,
        limitations=[
            (
                "The decision record is the authoritative score snapshot. The contribution "
                "ledger shown below is the current durable session ledger and may include "
                "events evaluated after this decision."
            ),
            (
                "A provisional twin attenuates newness signals; unusual behaviour is not "
                "by itself proof of fraud."
            ),
        ],
    )
