"""Merchant- and session-scoped loader for the advisory Intent Profiler.

Only derived, allowlisted fields cross this boundary. Raw IP addresses, device
identifiers, recipient addresses, payout notes, incident text, evidence payloads
and prior AI narratives are never copied into the profiler source model.
"""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import EntityNotFoundException
from app.core.security import AuthenticatedPrincipal
from app.intent.signals import as_utc
from app.models.canary import CanaryRecord
from app.models.event import SecurityEvent
from app.models.incident import IncidentRecord
from app.models.payout import PayoutRequestRecord
from app.models.session import SessionRecord
from app.models.twin import BehavioralTwin, SessionRiskStateRecord
from app.risk.twin import bucket_ip_address, hash_device, hash_recipient
from app.schemas.intent import (
    CanaryObservation,
    EventObservation,
    IncidentObservation,
    IntentExtractionPolicy,
    IntentSourceData,
    PayoutObservation,
    SequenceMarkerObservation,
    SessionObservation,
    SessionRiskStateObservation,
    TwinBaselineObservation,
)

_RECIPIENT_METADATA_KEYS = ("recipient_email", "recipient")


def ensure_session_access(
    db: Session, principal: AuthenticatedPrincipal, session_id: UUID
) -> SessionRecord:
    session = db.scalar(
        select(SessionRecord).where(
            SessionRecord.session_id == session_id,
            SessionRecord.merchant_id == principal.merchant_id,
        )
    )
    if session is None:
        raise EntityNotFoundException(message="Session not found.", code="SESSION_NOT_FOUND")
    return session


def _metadata_recipient(metadata: object) -> str | None:
    if not isinstance(metadata, dict):
        return None
    for key in _RECIPIENT_METADATA_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _bounded_int_map(value: object, limit: int) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, count in list(value.items())[:limit]:
        if not isinstance(count, (int, float)) or isinstance(count, bool):
            continue
        result[str(key)[:64]] = int(count)
    return result


def _bounded_strings(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item[:64] for item in value[:limit] if isinstance(item, str)]


def _shape_event(event: SecurityEvent) -> EventObservation:
    metadata = event.metadata_payload if isinstance(event.metadata_payload, dict) else {}
    return EventObservation(
        event_id=event.event_id,
        event_type=(event.event_type or "unknown")[:64],
        action=(event.action or "")[:64],
        occurred_at=as_utc(event.occurred_at),
        server_received_at=as_utc(event.server_received_at),
        device_hash=hash_device(event.device_id, settings.RISK_DEVICE_HASH_SALT),
        location_bucket=bucket_ip_address(event.ip_address),
        recipient_hash=hash_recipient(_metadata_recipient(metadata)),
    )


def _shape_twin(twin: BehavioralTwin | None) -> TwinBaselineObservation | None:
    if twin is None:
        return None
    return TwinBaselineObservation(
        sample_count=max(0, min(twin.sample_count, 1_000_000)),
        amount_count=max(0, min(twin.amount_count, 1_000_000)),
        total_amount=max(0.0, min(float(twin.total_amount or 0.0), 1_000_000_000.0)),
        confirmed_devices=_bounded_strings(twin.confirmed_devices, 500),
        confirmed_locations=_bounded_strings(twin.confirmed_locations, 500),
        payee_observations=_bounded_int_map(twin.payee_observations, 500),
        device_observations=_bounded_int_map(twin.device_observations, 500),
        location_observations=_bounded_int_map(twin.location_observations, 500),
        hour_histogram=_bounded_int_map(twin.hour_histogram, 24),
        last_updated_at=as_utc(twin.last_updated_at) if twin.last_updated_at else None,
    )


def _shape_risk_state(
    state: SessionRiskStateRecord | None,
) -> SessionRiskStateObservation | None:
    if state is None:
        return None
    markers: list[SequenceMarkerObservation] = []
    raw_markers = state.sequence_markers if isinstance(state.sequence_markers, list) else []
    for item in raw_markers[:500]:
        if not isinstance(item, dict):
            continue
        try:
            marker = SequenceMarkerObservation.model_validate(
                {
                    "marker_id": item.get("marker_id"),
                    "sequence_type": item.get("sequence_type"),
                    "recipient_hash": item.get("recipient_hash"),
                    "occurred_at": item.get("occurred_at"),
                }
            )
        except ValidationError:
            continue
        markers.append(marker.model_copy(update={"occurred_at": as_utc(marker.occurred_at)}))
    return SessionRiskStateObservation(
        current_score=max(0.0, min(float(state.current_score or 0.0), 100.0)),
        registered_payees=_bounded_strings(state.registered_payees, 500),
        sequence_markers=markers,
        consumed_markers=_bounded_strings(state.consumed_markers, 500),
        canary_seen=bool(state.canary_seen),
        last_evaluated_at=(as_utc(state.last_evaluated_at) if state.last_evaluated_at else None),
    )


def load_intent_source(
    db: Session,
    principal: AuthenticatedPrincipal,
    session_id: UUID,
    policy: IntentExtractionPolicy | None = None,
) -> IntentSourceData:
    policy = policy or IntentExtractionPolicy()
    session = ensure_session_access(db, principal, session_id)

    events = list(
        db.scalars(
            select(SecurityEvent)
            .where(
                SecurityEvent.session_id == session_id,
                SecurityEvent.merchant_id == principal.merchant_id,
            )
            .order_by(
                SecurityEvent.occurred_at.desc(),
                SecurityEvent.server_received_at.desc(),
                SecurityEvent.event_id.desc(),
            )
            .limit(policy.max_events)
        ).all()
    )
    payouts = list(
        db.scalars(
            select(PayoutRequestRecord)
            .where(
                PayoutRequestRecord.session_id == session_id,
                PayoutRequestRecord.merchant_id == principal.merchant_id,
            )
            .order_by(
                PayoutRequestRecord.created_at.desc(),
                PayoutRequestRecord.payout_id.desc(),
            )
            .limit(policy.max_payouts)
        ).all()
    )
    canaries = list(
        db.scalars(
            select(CanaryRecord)
            .where(
                CanaryRecord.session_id == session_id,
                CanaryRecord.merchant_id == principal.merchant_id,
            )
            .order_by(CanaryRecord.canary_id.desc())
            .limit(policy.max_canaries)
        ).all()
    )
    incidents = list(
        db.scalars(
            select(IncidentRecord)
            .where(
                IncidentRecord.session_id == session_id,
                IncidentRecord.merchant_id == principal.merchant_id,
            )
            .order_by(IncidentRecord.created_at.desc())
            .limit(policy.max_incidents)
        ).all()
    )
    twin = db.scalar(
        select(BehavioralTwin).where(
            BehavioralTwin.merchant_id == principal.merchant_id,
            BehavioralTwin.user_id == session.user_id,
        )
    )
    risk_state = db.scalar(
        select(SessionRiskStateRecord).where(
            SessionRiskStateRecord.session_id == session_id,
            SessionRiskStateRecord.merchant_id == principal.merchant_id,
        )
    )

    return IntentSourceData(
        session=SessionObservation(
            session_id=session.session_id,
            trust_level=(session.trust_level or "NORMAL")[:32],
            status=(session.status or "active")[:32],
            risk_score=max(0.0, min(float(session.risk_score or 0.0), 100.0)),
            last_activity_at=(
                as_utc(session.last_activity_at) if session.last_activity_at else None
            ),
        ),
        events=[_shape_event(event) for event in events],
        twin=_shape_twin(twin),
        risk_state=_shape_risk_state(risk_state),
        payouts=[
            PayoutObservation(
                payout_id=payout.payout_id,
                amount=max(0.0, float(payout.amount or 0.0)),
                status=(payout.status or "")[:64],
                provider_name=(payout.provider_name[:64] if payout.provider_name else None),
                created_at=as_utc(payout.created_at),
                executed_at=as_utc(payout.executed_at) if payout.executed_at else None,
            )
            for payout in payouts
        ],
        canaries=[
            CanaryObservation(
                canary_id=canary.canary_id,
                kind=(canary.kind or "")[:64],
                armed=bool(canary.armed),
                triggered_at=(as_utc(canary.triggered_at) if canary.triggered_at else None),
            )
            for canary in canaries
        ],
        incidents=[
            IncidentObservation(
                incident_id=incident.incident_id,
                status=(incident.status or "")[:32],
                trigger_reason=(incident.trigger_reason or "")[:96],
                risk_score=max(0.0, min(float(incident.risk_score or 0.0), 100.0)),
                created_at=as_utc(incident.created_at),
            )
            for incident in incidents
        ],
    )
