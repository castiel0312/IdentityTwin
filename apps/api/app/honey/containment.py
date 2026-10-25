from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evidence.hashchain import EvidenceChain
from app.honey.events import containment_event_bus
from app.models.incident import IncidentRecord
from app.models.session import SessionRecord
from app.schemas.incidents import IncidentSeverity, IncidentStatus
from app.schemas.sessions import SessionStatus, TrustLevel


def contain_canary_hit(db: Session, hit: dict) -> str | None:
    """Record a canary hit and isolate its observed session when it exists."""
    observed_session_id = hit.get("observed_session_id") or hit.get("session_id")
    evidence_payload = {
        "type": "canary_triggered",
        "session_id": observed_session_id,
        "canary_session_id": hit.get("session_id"),
        "canary_id": hit.get("canary_id"),
        "kind": hit.get("kind"),
        "tag": hit.get("tag"),
        "matched_in": hit.get("matched_in"),
        "cross_session_reuse": hit.get("cross_session_reuse", False),
    }
    chain = EvidenceChain(db)
    chain.append("canary_triggered", evidence_payload)

    try:
        session_uuid = UUID(str(observed_session_id))
    except (TypeError, ValueError):
        return None

    session = db.get(SessionRecord, session_uuid)
    if session is None:
        return None

    session.status = SessionStatus.REVOKED.value
    session.trust_level = TrustLevel.ISOLATED.value
    session.risk_score = 100.0

    incident = db.scalars(
        select(IncidentRecord)
        .where(IncidentRecord.session_id == session_uuid)
        .where(IncidentRecord.status == IncidentStatus.OPEN.value)
        .order_by(IncidentRecord.created_at.desc())
    ).first()
    if incident is None:
        incident = IncidentRecord(
            merchant_id=session.merchant_id,
            session_id=session_uuid,
            title="Canary interaction detected",
            description="The session accessed a uniquely tagged synthetic resource.",
            severity=IncidentSeverity.CRITICAL.value,
            status=IncidentStatus.OPEN.value,
            risk_score=100.0,
            trigger_reason="CANARY_INTERACTION",
            evidence_summary={"canary_hit": evidence_payload},
        )
        db.add(incident)
    else:
        incident.risk_score = 100.0
        incident.trigger_reason = "CANARY_INTERACTION"
        incident.evidence_summary = {
            **incident.evidence_summary,
            "canary_hit": evidence_payload,
        }
    db.commit()
    db.refresh(incident)

    chain.append(
        "session_isolated",
        {
            "type": "session_isolated",
            "session_id": str(session_uuid),
            "incident_id": str(incident.incident_id),
            "risk_after": 100,
            "trust_level": TrustLevel.ISOLATED.value,
            "plane": "real",
            "contributions": [{"signal": "canary_interaction", "points": 11}],
        },
    )
    chain.seal(incident.incident_id, session_uuid, session.merchant_id)
    containment_event_bus.publish(
        merchant_id=session.merchant_id,
        incident_id=incident.incident_id,
        session_id=session_uuid,
        severity=incident.severity,
        status=incident.status,
    )
    return str(incident.incident_id)
