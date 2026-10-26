from datetime import timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.evidence.hashchain import EvidenceChain
from app.models.evidence import EvidenceLogEntry, EvidencePayload
from app.models.incident import IncidentRecord
from app.models.principal import Merchant
from app.schemas.evidence import EvidenceSealDetailResponse, EvidenceSealListResponse
from app.services.evidence_query_service import get_seal_detail, list_seals

router = APIRouter(tags=["Evidence"])


def _get_incident_events(
    incident_id: str, principal: AuthenticatedPrincipal, db: Session
) -> tuple[IncidentRecord, list[tuple[EvidenceLogEntry, dict]]]:
    try:
        incident_uuid = UUID(incident_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Incident not found.") from None

    incident = db.get(IncidentRecord, incident_uuid)
    if incident is None or incident.merchant_id != principal.merchant_id:
        raise HTTPException(status_code=404, detail="Incident not found.")

    rows = db.execute(
        select(EvidenceLogEntry, EvidencePayload)
        .join(EvidencePayload, EvidencePayload.seq == EvidenceLogEntry.seq)
        .order_by(EvidenceLogEntry.seq.asc())
    ).all()
    session_id = str(incident.session_id) if incident.session_id else None
    events = [
        (entry, payload.payload)
        for entry, payload in rows
        if session_id and str(payload.payload.get("session_id")) == session_id
    ]
    return incident, events


@router.get(
    "/evidence/seals",
    response_model=EvidenceSealListResponse,
    summary="List incident evidence seals for the authenticated merchant",
)
def list_evidence_seals(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> EvidenceSealListResponse:
    return list_seals(db, principal, page=page, page_size=page_size)


@router.get(
    "/evidence/seals/{seal_id}",
    response_model=EvidenceSealDetailResponse,
    summary="Read one evidence seal and verify consistency of its recorded range",
    description=(
        "Seal-range verification checks sequence continuity, payload hashes, chain "
        "links and the sealed head. It is not a per-record notarisation."
    ),
)
def get_evidence_seal(
    seal_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> EvidenceSealDetailResponse:
    return get_seal_detail(db, principal, seal_id)


@router.get("/evidence/verify")
def verify_evidence(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return EvidenceChain(db).verify()


@router.get("/incidents/{incident_id}/timeline")
def get_timeline(
    incident_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    incident, events = _get_incident_events(incident_id, principal, db)
    timeline = []
    for entry, payload in events:
        timestamp = entry.created_at
        if timestamp and timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timeline.append(
            {
                "ts": timestamp.replace(microsecond=0).isoformat() if timestamp else None,
                "type": payload.get("type") or entry.event_ref,
                "summary": payload.get("summary")
                or payload.get("resource")
                or payload.get("payee")
                or entry.event_ref,
                "risk_after": payload.get("risk_after"),
                "trust_level": payload.get("trust_level"),
                "contributions": payload.get("contributions") or [],
                "evidence_seq": entry.seq,
                "evidence_hash": entry.hash,
                "plane": payload.get("plane")
                or ("honey" if "honey" in entry.event_ref.lower() else "real"),
            }
        )
    return {"incident_id": str(incident.incident_id), "timeline": timeline}


@router.get("/incidents/{incident_id}/attack-trace")
def get_attack_trace(
    incident_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    incident, events = _get_incident_events(incident_id, principal, db)
    merchant = db.get(Merchant, incident.merchant_id)
    event_payloads = [payload for _, payload in events]

    login = next((payload for payload in event_payloads if payload.get("type") == "login"), {})
    payee_event = next(
        (payload for payload in event_payloads if payload.get("type") == "payee_add"), {}
    )
    canary_event = next(
        (payload for payload in event_payloads if payload.get("type") == "canary_triggered"), {}
    )
    session_id = str(incident.session_id) if incident.session_id else "unknown"
    device_id = f"device-{session_id}"
    ip_id = f"ip-{session_id}"
    session_node_id = f"session-{session_id}"
    account_id = f"account-{incident.merchant_id}"
    nodes = [
        {
            "id": device_id,
            "type": "device",
            "label": login.get("device") or "Unknown device",
        },
        {"id": ip_id, "type": "ip", "label": login.get("ip") or "Unknown IP"},
        {"id": session_node_id, "type": "session", "label": session_id},
        {
            "id": account_id,
            "type": "account",
            "label": merchant.name if merchant else str(incident.merchant_id),
        },
    ]
    edges = [
        {"from": device_id, "to": ip_id, "relation": "used"},
        {"from": ip_id, "to": session_node_id, "relation": "origin"},
        {"from": session_node_id, "to": account_id, "relation": "acts_as"},
    ]

    payee = payee_event.get("payee")
    previous_node_id = account_id
    if payee:
        payee_node_id = f"payee-{payee}"
        nodes.append({"id": payee_node_id, "type": "payee", "label": str(payee)})
        edges.append({"from": session_node_id, "to": payee_node_id, "relation": "added"})
        previous_node_id = payee_node_id

    canary_tag = canary_event.get("tag")
    if canary_tag:
        canary_node_id = f"canary-{canary_event.get('canary_id', canary_tag)}"
        nodes.append({"id": canary_node_id, "type": "canary", "label": str(canary_tag)})
        edges.append({"from": previous_node_id, "to": canary_node_id, "relation": "accessed"})

    return {"incident_id": str(incident.incident_id), "nodes": nodes, "edges": edges}
