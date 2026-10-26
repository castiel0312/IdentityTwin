"""Payout read projections.

Read-only by construction: this service never executes, retries or reconciles a
payout. It projects records written by the Trust Gateway.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException
from app.core.security import AuthenticatedPrincipal
from app.db.repositories.twin_repo import TwinRepository
from app.models.agent import AgenticCommerceAudit, AgentRegistration
from app.models.evidence import EvidenceLogEntry, EvidencePayload, IncidentSeal
from app.models.idempotency import IdempotencyRecord
from app.models.incident import IncidentRecord
from app.models.payout import PayoutRequestRecord
from app.models.risk import RiskDecisionRecord
from app.models.session import SessionRecord
from app.risk.config import get_risk_config
from app.schemas.payout_queries import (
    PayoutAgentView,
    PayoutDecisionView,
    PayoutDetailResponse,
    PayoutEvidenceEntry,
    PayoutEvidenceSeal,
    PayoutEvidenceView,
    PayoutIdempotencyView,
    PayoutIncidentReference,
    PayoutListItem,
    PayoutListResponse,
    PayoutProviderView,
    PayoutRequestView,
    PayoutSessionView,
    PayoutStepUpView,
    PayoutTimelineItem,
)
from app.services.redaction import redact

RECONCILIATION_STATUSES = {"provider_executed", "needs_reconciliation"}
PROVIDER_FAILURE_STATUSES = {"failed", "provider_denied", "provider_execution_failed"}

SIGNAL_WEIGHTS = {
    "NEW_DEVICE": "weight_new_device",
    "NEW_LOCATION": "weight_new_location",
    "UNUSUAL_TIME": "weight_unusual_time",
    "NEW_PAYEE": "weight_new_payee",
    "LARGE_PAYOUT": "weight_large_payout",
    "NEW_PAYEE_LARGE_PAYOUT": "weight_new_payee_large_payout",
    "PAYEE_ADD_THEN_PAYOUT": "weight_payee_add_then_payout",
    "CANARY_INTERACTION": "weight_canary_interaction",
}


def configured_signal_weights() -> dict[str, float]:
    config = get_risk_config()
    return {name: float(getattr(config, attr)) for name, attr in SIGNAL_WEIGHTS.items()}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _sort_expression(sort: str):
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    if key == "amount":
        column = PayoutRequestRecord.amount
    elif key == "risk_score":
        column = RiskDecisionRecord.risk_score
    elif key == "status":
        column = PayoutRequestRecord.status
    else:
        column = PayoutRequestRecord.created_at
    return column.desc() if descending else column.asc()


def _agent_metadata(
    db: Session, merchant_id: UUID, payout_ids: list[UUID]
) -> dict[UUID, tuple[AgenticCommerceAudit, AgentRegistration | None]]:
    if not payout_ids:
        return {}
    rows = db.execute(
        select(AgenticCommerceAudit, AgentRegistration)
        .outerjoin(
            AgentRegistration,
            AgentRegistration.agent_id == AgenticCommerceAudit.agent_id,
        )
        .where(
            AgenticCommerceAudit.merchant_id == merchant_id,
            AgenticCommerceAudit.payout_id.in_(payout_ids),
        )
        .order_by(AgenticCommerceAudit.created_at.desc())
    ).all()
    result: dict[UUID, tuple[AgenticCommerceAudit, AgentRegistration | None]] = {}
    for audit, agent in rows:
        if audit.payout_id is not None and audit.payout_id not in result:
            result[audit.payout_id] = (audit, agent)
    return result


def _idempotency_metadata(
    db: Session, merchant_id: UUID, keys: list[str]
) -> dict[str, IdempotencyRecord]:
    if not keys:
        return {}
    rows = db.scalars(
        select(IdempotencyRecord).where(
            IdempotencyRecord.merchant_id == merchant_id,
            IdempotencyRecord.idempotency_key.in_(keys),
        )
    ).all()
    return {row.idempotency_key: row for row in rows}


def _reconciliation_required(
    payout: PayoutRequestRecord, idempotency: IdempotencyRecord | None
) -> bool:
    if payout.status in RECONCILIATION_STATUSES:
        return True
    return bool(idempotency and idempotency.status in RECONCILIATION_STATUSES)


def _to_list_item(
    payout: PayoutRequestRecord,
    decision: RiskDecisionRecord,
    idempotency: IdempotencyRecord | None,
    agent: tuple[AgenticCommerceAudit, AgentRegistration | None] | None,
) -> PayoutListItem:
    return PayoutListItem(
        payout_id=payout.payout_id,
        merchant_id=payout.merchant_id,
        session_id=payout.session_id,
        amount=payout.amount,
        currency=payout.currency,
        recipient_email=payout.recipient_email,
        reference_note=payout.reference_note,
        risk_score=decision.risk_score,
        trust_level=decision.trust_level,
        action=decision.action,
        routing_destination=decision.routing_destination,
        reason_codes=list(decision.reason_codes or []),
        status=payout.status,
        provider_name=payout.provider_name,
        provider_reference=payout.provider_reference,
        created_at=payout.created_at,
        executed_at=payout.executed_at,
        reconciliation_required=_reconciliation_required(payout, idempotency),
        agent_id=agent[0].agent_id if agent else None,
        agent_display_name=agent[1].display_name if agent and agent[1] else None,
    )


def list_payouts(
    db: Session,
    principal: AuthenticatedPrincipal,
    *,
    q: str | None = None,
    status: str | None = None,
    trust_level: str | None = None,
    provider: str | None = None,
    initiator: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    sort: str = "-created_at",
    page: int = 1,
    page_size: int = 25,
) -> PayoutListResponse:
    filters = [PayoutRequestRecord.merchant_id == principal.merchant_id]
    if status:
        filters.append(PayoutRequestRecord.status == status.strip().lower())
    if provider:
        filters.append(PayoutRequestRecord.provider_name == provider.strip())
    if trust_level:
        filters.append(RiskDecisionRecord.trust_level == trust_level.strip().upper())
    if start:
        filters.append(PayoutRequestRecord.created_at >= start)
    if end:
        filters.append(PayoutRequestRecord.created_at <= end)
    if q:
        term = f"%{q.strip()}%"
        filters.append(
            or_(
                cast(PayoutRequestRecord.payout_id, String).ilike(term),
                PayoutRequestRecord.recipient_email.ilike(term),
                PayoutRequestRecord.reference_note.ilike(term),
                PayoutRequestRecord.provider_reference.ilike(term),
                PayoutRequestRecord.idempotency_key.ilike(term),
            )
        )

    agent_payout_ids = select(AgenticCommerceAudit.payout_id).where(
        AgenticCommerceAudit.merchant_id == principal.merchant_id,
        AgenticCommerceAudit.payout_id.is_not(None),
    )
    if initiator == "agent":
        filters.append(PayoutRequestRecord.payout_id.in_(agent_payout_ids))
    elif initiator == "human":
        filters.append(PayoutRequestRecord.payout_id.not_in(agent_payout_ids))

    total = (
        db.scalar(
            select(func.count())
            .select_from(PayoutRequestRecord)
            .join(
                RiskDecisionRecord,
                RiskDecisionRecord.decision_id == PayoutRequestRecord.decision_id,
            )
            .where(*filters)
        )
        or 0
    )

    offset = (page - 1) * page_size
    rows = db.execute(
        select(PayoutRequestRecord, RiskDecisionRecord)
        .join(
            RiskDecisionRecord,
            RiskDecisionRecord.decision_id == PayoutRequestRecord.decision_id,
        )
        .where(*filters)
        .order_by(_sort_expression(sort))
        .limit(page_size)
        .offset(offset)
    ).all()

    payout_ids = [payout.payout_id for payout, _ in rows]
    keys = [payout.idempotency_key for payout, _ in rows]
    agents = _agent_metadata(db, principal.merchant_id, payout_ids)
    idempotency = _idempotency_metadata(db, principal.merchant_id, keys)

    items = [
        _to_list_item(
            payout,
            decision,
            idempotency.get(payout.idempotency_key),
            agents.get(payout.payout_id),
        )
        for payout, decision in rows
    ]
    return PayoutListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


def _load_evidence(
    db: Session, session_id: UUID, incident_ids: list[UUID]
) -> tuple[PayoutEvidenceView, IncidentSeal | None]:
    rows = db.execute(
        select(EvidenceLogEntry, EvidencePayload)
        .join(EvidencePayload, EvidencePayload.seq == EvidenceLogEntry.seq)
        .order_by(EvidenceLogEntry.seq.asc())
    ).all()
    entries = [
        PayoutEvidenceEntry(
            seq=entry.seq,
            event_ref=entry.event_ref,
            hash=entry.hash,
            created_at=entry.created_at,
        )
        for entry, payload in rows
        if str((payload.payload or {}).get("session_id")) == str(session_id)
    ][:100]

    seal = None
    if incident_ids:
        seal = db.scalars(
            select(IncidentSeal)
            .where(IncidentSeal.incident_id.in_(incident_ids))
            .order_by(IncidentSeal.sealed_at.desc())
        ).first()
    if seal is None:
        seal = db.scalars(
            select(IncidentSeal)
            .where(IncidentSeal.session_id == session_id)
            .order_by(IncidentSeal.sealed_at.desc())
        ).first()

    seal_view = (
        PayoutEvidenceSeal(
            seal_id=seal.seal_id,
            start_seq=seal.start_seq,
            end_seq=seal.end_seq,
            head_hash=seal.head_hash,
            sealed_at=seal.sealed_at,
        )
        if seal
        else None
    )
    return PayoutEvidenceView(entries=entries, seal=seal_view), seal


def get_payout_detail(
    db: Session, principal: AuthenticatedPrincipal, payout_id: UUID
) -> PayoutDetailResponse:
    payout = db.get(PayoutRequestRecord, payout_id)
    if payout is None or payout.merchant_id != principal.merchant_id:
        # Cross-tenant and missing records are indistinguishable by design.
        raise EntityNotFoundException(
            message="Payout not found.", code="PAYOUT_NOT_FOUND"
        )

    decision = db.get(RiskDecisionRecord, payout.decision_id)
    if decision is None:
        raise EntityNotFoundException(
            message="Risk decision for this payout is unavailable.",
            code="RISK_DECISION_NOT_FOUND",
        )
    session = db.get(SessionRecord, payout.session_id)
    if session is None:
        raise EntityNotFoundException(
            message="Session for this payout is unavailable.",
            code="SESSION_NOT_FOUND",
        )

    idempotency = db.scalars(
        select(IdempotencyRecord).where(
            IdempotencyRecord.merchant_id == principal.merchant_id,
            IdempotencyRecord.idempotency_key == payout.idempotency_key,
        )
    ).first()
    agents = _agent_metadata(db, principal.merchant_id, [payout.payout_id])
    agent_pair = agents.get(payout.payout_id)
    agent_view = (
        PayoutAgentView(
            agent_id=agent_pair[0].agent_id,
            display_name=(
                agent_pair[1].display_name
                if agent_pair[1]
                else agent_pair[0].agent_id.hex[:12]
            ),
            grant_id=agent_pair[0].grant_id,
            status=agent_pair[0].status,
            intent=agent_pair[0].outcome,
            audit_id=agent_pair[0].audit_id,
        )
        if agent_pair
        else None
    )
    item = _to_list_item(
        payout, decision, idempotency, agent_pair
    )

    incidents = list(
        db.scalars(
            select(IncidentRecord)
            .where(
                IncidentRecord.merchant_id == principal.merchant_id,
                IncidentRecord.session_id == payout.session_id,
            )
            .order_by(IncidentRecord.created_at.desc())
            .limit(10)
        ).all()
    )
    incident_refs = [
        PayoutIncidentReference(
            incident_id=incident.incident_id,
            title=incident.title,
            severity=incident.severity,
            status=incident.status,
            risk_score=incident.risk_score,
            trigger_reason=incident.trigger_reason,
            sealed_at=_as_utc(incident.sealed_at),
            created_at=incident.created_at,
        )
        for incident in incidents
    ]
    evidence, _ = _load_evidence(
        db, payout.session_id, [incident.incident_id for incident in incidents]
    )

    reason_codes = list(decision.reason_codes or [])
    step_up_required = decision.action == "REQUIRE_STEP_UP"
    step_up_verified = "RESTRICTED_STEP_UP_VERIFIED_PAYOUT_PERMITTED" in reason_codes
    step_up = PayoutStepUpView(
        required=step_up_required or decision.trust_level == "RESTRICTED",
        verified=step_up_verified,
        evidence=(
            "Server reason code confirms a verified single-use step-up challenge "
            "authorized this payout."
            if step_up_verified
            else (
                "Policy requires a step-up challenge before this payout can execute."
                if step_up_required or decision.trust_level == "RESTRICTED"
                else None
            )
        ),
    )

    timeline: list[PayoutTimelineItem] = [
        PayoutTimelineItem(
            key="decision",
            label="Risk decision evaluated",
            status="completed",
            occurred_at=decision.evaluated_at,
            detail=(
                f"Score {decision.risk_score:.1f} · {decision.trust_level} · "
                f"{decision.action}"
            ),
        )
    ]
    if idempotency is not None:
        timeline.append(
            PayoutTimelineItem(
                key="idempotency",
                label="Idempotency record claimed",
                status=idempotency.status,
                occurred_at=_as_utc(idempotency.created_at),
                detail=f"Key {idempotency.idempotency_key}",
            )
        )
    timeline.append(
        PayoutTimelineItem(
            key="payout",
            label="Payout recorded",
            status=payout.status,
            occurred_at=_as_utc(payout.created_at),
            detail=f"{payout.amount:.2f} {payout.currency} → {payout.recipient_email}",
        )
    )
    if step_up_required:
        timeline.append(
            PayoutTimelineItem(
                key="step_up",
                label="Step-up challenge required",
                status="verified" if step_up_verified else "required",
                occurred_at=decision.evaluated_at,
                detail=step_up.evidence,
            )
        )
    if payout.executed_at is not None:
        timeline.append(
            PayoutTimelineItem(
                key="provider",
                label=(
                    "Synthetic decoy executed"
                    if payout.status == "decoy_completed"
                    else "Provider dispatched"
                ),
                status=payout.status,
                occurred_at=_as_utc(payout.executed_at),
                detail=payout.provider_reference,
            )
        )
    if payout.status in PROVIDER_FAILURE_STATUSES:
        timeline.append(
            PayoutTimelineItem(
                key="provider_failure",
                label="Provider reported failure",
                status=payout.status,
                occurred_at=_as_utc(payout.updated_at),
                detail=payout.provider_reference,
            )
        )
    if payout.status == "blocked":
        timeline.append(
            PayoutTimelineItem(
                key="blocked",
                label="Blocked by isolation policy",
                status="blocked",
                occurred_at=_as_utc(payout.updated_at),
                detail="Payment provider was never contacted.",
            )
        )
    if _reconciliation_required(payout, idempotency):
        timeline.append(
            PayoutTimelineItem(
                key="reconciliation",
                label="Reconciliation required",
                status="needs_reconciliation",
                occurred_at=_as_utc(
                    idempotency.updated_at if idempotency else payout.updated_at
                ),
                detail=(
                    "The provider may already have executed this payout. "
                    "The gateway will not re-execute it; reconciliation is authoritative."
                ),
            )
        )

    return PayoutDetailResponse(
        payout=item,
        request=PayoutRequestView(
            recipient_email=payout.recipient_email,
            amount=payout.amount,
            currency=payout.currency,
            reference_note=payout.reference_note,
            idempotency_key=payout.idempotency_key,
        ),
        decision=PayoutDecisionView(
            decision_id=decision.decision_id,
            risk_score=decision.risk_score,
            trust_level=decision.trust_level,
            action=decision.action,
            routing_destination=decision.routing_destination,
            reason_codes=reason_codes,
            risk_signals=dict(decision.risk_signals or {}),
            signal_weights=configured_signal_weights(),
            evaluated_at=decision.evaluated_at,
        ),
        provider=PayoutProviderView(
            name=payout.provider_name,
            reference=payout.provider_reference,
            executed_at=_as_utc(payout.executed_at),
            payload=redact(dict(payout.provider_payload or {})),
        ),
        idempotency=(
            PayoutIdempotencyView(
                status=idempotency.status,
                request_hash=idempotency.request_hash,
                response_code=idempotency.response_code,
                expires_at=_as_utc(idempotency.expires_at),
                updated_at=_as_utc(idempotency.updated_at),
                reconciliation_required=_reconciliation_required(payout, idempotency),
            )
            if idempotency
            else None
        ),
        session=PayoutSessionView(
            session_id=session.session_id,
            status=session.status,
            trust_level=session.trust_level,
            risk_score=session.risk_score,
            device_fingerprint=session.device_fingerprint,
            ip_address=session.ip_address,
            created_at=session.created_at,
            last_activity_at=session.last_activity_at,
        ),
        incidents=incident_refs,
        evidence=evidence,
        step_up=step_up,
        agent=agent_view,
        timeline=timeline,
    )


def payout_items_for_ids(
    db: Session, merchant_id: UUID, payout_ids: list[UUID]
) -> list[PayoutListItem]:
    """Project a bounded set of payouts for embedded agent/session views."""
    if not payout_ids:
        return []
    rows = db.execute(
        select(PayoutRequestRecord, RiskDecisionRecord)
        .join(
            RiskDecisionRecord,
            RiskDecisionRecord.decision_id == PayoutRequestRecord.decision_id,
        )
        .where(
            PayoutRequestRecord.merchant_id == merchant_id,
            PayoutRequestRecord.payout_id.in_(payout_ids),
        )
        .order_by(PayoutRequestRecord.created_at.desc())
    ).all()
    agents = _agent_metadata(db, merchant_id, [payout.payout_id for payout, _ in rows])
    idempotency = _idempotency_metadata(
        db, merchant_id, [payout.idempotency_key for payout, _ in rows]
    )
    return [
        _to_list_item(
            payout,
            decision,
            idempotency.get(payout.idempotency_key),
            agents.get(payout.payout_id),
        )
        for payout, decision in rows
    ]


def twin_comparison_for_session(db: Session, merchant_id: UUID, user_id: UUID):
    twin = TwinRepository(db).get_twin(merchant_id, user_id)
    if twin is None:
        return None
    return {
        "sample_count": twin.sample_count,
        "is_provisional": twin.sample_count < get_risk_config().min_samples,
        "confirmed_device_count": len(twin.confirmed_devices or []),
        "confirmed_location_count": len(twin.confirmed_locations or []),
        "confirmed_payee_count": sum(
            1
            for count in (twin.payee_observations or {}).values()
            if int(count) >= get_risk_config().payee_confirm_observations
        ),
        "pending_payee_count": sum(
            1
            for count in (twin.payee_observations or {}).values()
            if int(count) < get_risk_config().payee_confirm_observations
        ),
    }
