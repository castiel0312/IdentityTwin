from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evidence.hashchain import EvidenceChain
from app.models.evidence import IncidentSeal


def append_honey_evidence(db: Session, event_ref: str, payload: dict) -> None:
    session_id = payload.get("session_id")
    try:
        session_uuid = UUID(str(session_id)) if session_id else None
    except ValueError:
        session_uuid = None
    if (
        session_uuid is not None
        and db.scalars(select(IncidentSeal).where(IncidentSeal.session_id == session_uuid)).first()
    ):
        return
    EvidenceChain(db).append(event_ref, payload)
