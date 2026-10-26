"""Session investigation projections: events, payouts, incidents and sequences."""

from datetime import timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException
from app.core.security import AuthenticatedPrincipal
from app.db.repositories.twin_repo import TwinRepository
from app.models.canary import CanaryRecord
from app.models.event import SecurityEvent
from app.models.incident import IncidentRecord
from app.models.payout import PayoutRequestRecord
from app.models.session import SessionRecord
from app.risk.config import get_risk_config
from app.schemas.identities import TwinSummary
from app.schemas.incidents import IncidentResponse
from app.schemas.session_activity import (
    SequenceEventView,
    SessionActivityResponse,
    SessionCanaryView,
    SessionEventView,
    SessionRiskLedgerView,
    SessionSequencesView,
    SessionSequenceView,
)
from app.schemas.sessions import SessionResponse
from app.services.payout_query_service import payout_items_for_ids


def _session_for_merchant(
    db: Session, principal: AuthenticatedPrincipal, session_id: UUID
) -> SessionRecord:
    session = db.get(SessionRecord, session_id)
    if session is None or session.merchant_id != principal.merchant_id:
        raise EntityNotFoundException(
            message="Session not found.", code="SESSION_NOT_FOUND"
        )
    return session


def get_session_activity(
    db: Session, principal: AuthenticatedPrincipal, session_id: UUID
) -> SessionActivityResponse:
    session = _session_for_merchant(db, principal, session_id)
    events = list(
        db.scalars(
            select(SecurityEvent)
            .where(SecurityEvent.session_id == session_id)
            .order_by(SecurityEvent.occurred_at.desc())
            .limit(250)
        ).all()
    )
    payouts = payout_items_for_ids(
        db,
        principal.merchant_id,
        list(
            db.scalars(
                select(PayoutRequestRecord.payout_id)
                .where(PayoutRequestRecord.session_id == session_id)
                .order_by(PayoutRequestRecord.created_at.desc())
                .limit(50)
            ).all()
        ),
    )
    incidents = [
        IncidentResponse.model_validate(incident)
        for incident in db.scalars(
            select(IncidentRecord)
            .where(
                IncidentRecord.merchant_id == principal.merchant_id,
                IncidentRecord.session_id == session_id,
            )
            .order_by(IncidentRecord.created_at.desc())
            .limit(20)
        ).all()
    ]
    canaries = [
        SessionCanaryView(
            canary_id=canary.canary_id,
            kind=canary.kind,
            tag=canary.tag,
            armed=canary.armed,
            triggered_at=(
                canary.triggered_at
                if canary.triggered_at is None or canary.triggered_at.tzinfo
                else canary.triggered_at.replace(tzinfo=timezone.utc)
            ),
        )
        for canary in db.scalars(
            select(CanaryRecord)
            .where(CanaryRecord.session_id == session_id)
            .order_by(CanaryRecord.kind.asc())
        ).all()
    ]

    repo = TwinRepository(db)
    record = repo.get_session_state(session_id)
    state = repo.to_state(record) if record is not None else None
    ledger = SessionRiskLedgerView(
        current_score=state.current_score if state else session.risk_score,
        carried_forward=state.carried_forward if state else 0.0,
        raw_points_sum=state.raw_points_sum if state else 0.0,
        decay_points_total=state.decay_points_total if state else 0.0,
        canary_points=state.canary_points if state else 0.0,
        canary_seen=state.canary_seen if state else False,
        latched_signals=state.latched_signals if state else [],
        contributions=state.contributions if state else [],
        last_evaluated_at=(
            (state.updated_at if state else None)
            or (record.last_evaluated_at if record else None)
        ),
    )

    window_seconds = get_risk_config().sequence_window_seconds
    marker_views: list[SessionSequenceView] = []
    ordered_events = sorted(events, key=lambda event: event.occurred_at)
    for marker in state.sequence_markers if state else []:
        marker_time = marker.occurred_at
        marker_utc = (
            marker_time if marker_time.tzinfo else marker_time.replace(tzinfo=timezone.utc)
        )
        related = [
            event
            for event in ordered_events
            if 0
            <= (marker_utc - (
                event.occurred_at
                if event.occurred_at.tzinfo
                else event.occurred_at.replace(tzinfo=timezone.utc)
            )).total_seconds()
            <= window_seconds
        ][-20:]
        first_time = (
            related[0].occurred_at
            if related
            else marker_time
        )
        first_utc = (
            first_time if first_time.tzinfo else first_time.replace(tzinfo=timezone.utc)
        )
        marker_views.append(
            SessionSequenceView(
                marker_id=marker.marker_id,
                sequence_type=marker.sequence_type,
                occurred_at=marker_utc,
                elapsed_seconds=round(
                    max(0.0, (marker_utc - first_utc).total_seconds()), 1
                ),
                recipient_hash=marker.recipient_hash,
                events=[
                    SequenceEventView(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        action=event.action,
                        occurred_at=(
                            event.occurred_at
                            if event.occurred_at.tzinfo
                            else event.occurred_at.replace(tzinfo=timezone.utc)
                        ),
                        elapsed_seconds=round(
                            max(
                                0.0,
                                (
                                    (
                                        event.occurred_at
                                        if event.occurred_at.tzinfo
                                        else event.occurred_at.replace(tzinfo=timezone.utc)
                                    )
                                    - first_utc
                                ).total_seconds(),
                            ),
                            1,
                        ),
                    )
                    for event in related
                ],
            )
        )

    devices = sorted(
        {
            value
            for value in [
                session.device_fingerprint,
                *[event.device_id for event in events],
            ]
            if value
        }
    )
    locations = sorted(
        {
            value
            for value in [session.ip_address, *[event.ip_address for event in events]]
            if value
        }
    )

    twin_record = repo.get_twin(principal.merchant_id, session.user_id)
    twin = None
    if twin_record is not None:
        config = get_risk_config()
        payees = twin_record.payee_observations or {}
        twin = TwinSummary(
            twin_id=twin_record.twin_id,
            sample_count=twin_record.sample_count,
            is_provisional=twin_record.sample_count < config.min_samples,
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
            active_hours=sorted(
                int(hour)
                for hour, count in (twin_record.hour_histogram or {}).items()
                if int(count) > 0
            ),
            amount_count=twin_record.amount_count,
            last_updated_at=twin_record.last_updated_at,
        )

    return SessionActivityResponse(
        session=SessionResponse.model_validate(session),
        events=[
            SessionEventView(
                event_id=event.event_id,
                event_type=event.event_type,
                action=event.action,
                occurred_at=(
                    event.occurred_at
                    if event.occurred_at.tzinfo
                    else event.occurred_at.replace(tzinfo=timezone.utc)
                ),
                server_received_at=(
                    event.server_received_at
                    if event.server_received_at.tzinfo
                    else event.server_received_at.replace(tzinfo=timezone.utc)
                ),
                device_id=event.device_id,
                ip_address=event.ip_address,
                metadata=dict(event.metadata_payload or {}),
            )
            for event in events
        ],
        payouts=payouts,
        incidents=incidents,
        risk_ledger=ledger,
        sequences=SessionSequencesView(
            window_seconds=window_seconds, markers=marker_views
        ),
        canaries=canaries,
        devices=devices,
        locations=locations,
        twin=twin,
    )
