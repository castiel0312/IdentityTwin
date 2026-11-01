import uuid
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import OwnershipMismatchException
from app.db.repositories.incident_repo import IncidentRepository
from app.evidence.hashchain import EvidenceChain
from app.models.incident import IncidentRecord
from app.models.session import SessionRecord
from app.schemas.incidents import IncidentSeverity, IncidentStatus
from app.schemas.sessions import SessionStatus, TrustLevel


def isolate_session_and_open_incident(
    db: Session,
    session: SessionRecord,
    merchant_id: UUID,
    user_id: UUID,
    source: Literal["gateway", "event_ingestion"],
    risk_score: float,
    action: str,
    trigger_reason: str,
    evidence_summary: dict[str, Any] | None = None,
    title: str = "Immediate Security Isolation Triggered",
) -> IncidentRecord:
    """
    Centralized handler for Level 3 ISOLATED enforcement.
    Revokes the session and creates a critical security incident for analyst review.
    Shared by both event ingestion and protected payout gateway paths.
    """
    if session.merchant_id != merchant_id or session.user_id != user_id:
        raise OwnershipMismatchException(
            message="Cannot isolate a session outside the authenticated owner scope."
        )

    session.status = SessionStatus.REVOKED.value
    session.trust_level = TrustLevel.ISOLATED.value
    session.risk_score = risk_score
    incident = IncidentRecord(
        incident_id=uuid.uuid4(),
        merchant_id=merchant_id,
        session_id=session.session_id,
        title=title,
        description=(
            f"Session isolated due to critical risk evaluation (score={risk_score}). "
            f"Action: {action}"
        ),
        severity=IncidentSeverity.CRITICAL.value,
        status=IncidentStatus.OPEN.value,
        risk_score=risk_score,
        trigger_reason=trigger_reason or "ANOMALY_ISOLATION",
        evidence_summary=evidence_summary or {},
    )
    IncidentRepository(db).create(incident)
    chain = EvidenceChain(db)
    isolation_event_type = "gateway_blocked" if source == "gateway" else "risk_isolation_triggered"
    chain.append(
        isolation_event_type,
        {
            "type": isolation_event_type,
            "session_id": str(session.session_id),
            "merchant_id": str(merchant_id),
            "incident_id": str(incident.incident_id),
            "source": source,
            "action": action,
            "trigger_reason": incident.trigger_reason,
            "risk_score": risk_score,
            "evidence_summary": incident.evidence_summary,
        },
    )
    chain.append(
        "session_isolated",
        {
            "type": "session_isolated",
            "session_id": str(session.session_id),
            "merchant_id": str(merchant_id),
            "incident_id": str(incident.incident_id),
            "risk_after": risk_score,
            "trust_level": TrustLevel.ISOLATED.value,
            "plane": "real",
            "contributions": [{"signal": "gateway_block", "points": risk_score}],
        },
    )
    chain.seal(incident.incident_id, session.session_id, merchant_id)
    return incident
