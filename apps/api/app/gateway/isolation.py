import uuid
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.repositories.incident_repo import IncidentRepository
from app.models.incident import IncidentRecord
from app.models.session import SessionRecord
from app.schemas.incidents import IncidentSeverity, IncidentStatus
from app.schemas.sessions import SessionStatus


def isolate_session_and_open_incident(
    db: Session,
    session: SessionRecord,
    merchant_id: UUID,
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
    session.status = SessionStatus.REVOKED.value
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
    return incident
