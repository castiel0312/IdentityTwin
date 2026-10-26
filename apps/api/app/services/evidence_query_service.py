"""Evidence seal read projections and seal-range consistency checks."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException
from app.core.security import AuthenticatedPrincipal
from app.evidence.hashchain import GENESIS_PREV_HASH, compute_hash, payload_hash
from app.models.evidence import (
    EvidenceChainHead,
    EvidenceLogEntry,
    EvidencePayload,
    IncidentSeal,
)
from app.models.incident import IncidentRecord
from app.schemas.evidence import (
    EvidenceEntryView,
    EvidenceSealDetailResponse,
    EvidenceSealListResponse,
    EvidenceSealSummary,
    SealVerificationView,
)
from app.services.redaction import redact

LIMITATIONS = [
    "Hash-chain verification establishes consistency with the available chain and checkpoint.",
    "It does not prove that a database administrator cannot rewrite or restore the database.",
    "Seal-range verification is not a per-record notarisation and is not a signature approval.",
]


def _summary(
    seal: IncidentSeal, incident: IncidentRecord | None
) -> EvidenceSealSummary:
    return EvidenceSealSummary(
        seal_id=seal.seal_id,
        incident_id=seal.incident_id,
        incident_title=incident.title if incident else "Incident unavailable",
        incident_status=incident.status if incident else "UNKNOWN",
        session_id=seal.session_id,
        merchant_id=seal.merchant_id,
        start_seq=seal.start_seq,
        end_seq=seal.end_seq,
        head_hash=seal.head_hash,
        sealed_at=seal.sealed_at,
    )


def list_seals(
    db: Session,
    principal: AuthenticatedPrincipal,
    *,
    page: int = 1,
    page_size: int = 25,
) -> EvidenceSealListResponse:
    total = (
        db.scalar(
            select(func.count())
            .select_from(IncidentSeal)
            .where(IncidentSeal.merchant_id == principal.merchant_id)
        )
        or 0
    )
    offset = (page - 1) * page_size
    rows = db.execute(
        select(IncidentSeal, IncidentRecord)
        .outerjoin(
            IncidentRecord, IncidentRecord.incident_id == IncidentSeal.incident_id
        )
        .where(IncidentSeal.merchant_id == principal.merchant_id)
        .order_by(IncidentSeal.sealed_at.desc())
        .limit(page_size)
        .offset(offset)
    ).all()
    checkpoint = db.get(EvidenceChainHead, 1)
    return EvidenceSealListResponse(
        items=[_summary(seal, incident) for seal, incident in rows],
        total=total,
        page=page,
        page_size=page_size,
        chain_head_hash=checkpoint.hash if checkpoint and checkpoint.seq else None,
        chain_checkpoint_seq=checkpoint.seq if checkpoint else None,
    )


def get_seal_detail(
    db: Session, principal: AuthenticatedPrincipal, seal_id: UUID
) -> EvidenceSealDetailResponse:
    seal = db.get(IncidentSeal, seal_id)
    if seal is None or seal.merchant_id != principal.merchant_id:
        raise EntityNotFoundException(
            message="Evidence seal not found.", code="EVIDENCE_SEAL_NOT_FOUND"
        )
    incident = db.get(IncidentRecord, seal.incident_id)
    rows = db.execute(
        select(EvidenceLogEntry, EvidencePayload)
        .join(EvidencePayload, EvidencePayload.seq == EvidenceLogEntry.seq)
        .where(
            EvidenceLogEntry.seq >= seal.start_seq,
            EvidenceLogEntry.seq <= seal.end_seq,
        )
        .order_by(EvidenceLogEntry.seq.asc())
    ).all() if seal.start_seq and seal.end_seq else []

    entries = [
        EvidenceEntryView(
            seq=entry.seq,
            event_ref=entry.event_ref,
            payload_hash=entry.payload_hash,
            prev_hash=entry.prev_hash,
            hash=entry.hash,
            created_at=entry.created_at,
            payload=redact(dict(payload.payload or {})),
        )
        for entry, payload in rows
    ]

    previous = db.get(EvidenceLogEntry, seal.start_seq - 1) if seal.start_seq > 1 else None
    expected_prev = previous.hash if previous else GENESIS_PREV_HASH
    verification = SealVerificationView(
        valid=True,
        checked=0,
        head_matches=False,
    )
    if not rows:
        verification = SealVerificationView(
            valid=False,
            checked=0,
            reason="seal_range_empty",
            head_matches=seal.start_seq == 0 and seal.end_seq == 0,
            first_broken_seq=None,
        )
    else:
        expected_seq = seal.start_seq
        for entry, payload in rows:
            if entry.seq != expected_seq:
                verification = SealVerificationView(
                    valid=False,
                    checked=expected_seq - seal.start_seq,
                    reason="sequence_gap",
                    head_matches=False,
                    first_broken_seq=expected_seq,
                )
                break
            if entry.prev_hash != expected_prev:
                verification = SealVerificationView(
                    valid=False,
                    checked=entry.seq - seal.start_seq,
                    reason="prev_hash_mismatch",
                    head_matches=False,
                    first_broken_seq=entry.seq,
                )
                break
            if payload is None or payload_hash(payload.payload) != entry.payload_hash:
                verification = SealVerificationView(
                    valid=False,
                    checked=entry.seq - seal.start_seq,
                    reason="payload_hash_mismatch",
                    head_matches=False,
                    first_broken_seq=entry.seq,
                )
                break
            if (
                compute_hash(entry.seq, entry.event_ref, entry.payload_hash, entry.prev_hash)
                != entry.hash
            ):
                verification = SealVerificationView(
                    valid=False,
                    checked=entry.seq - seal.start_seq,
                    reason="hash_mismatch",
                    head_matches=False,
                    first_broken_seq=entry.seq,
                )
                break
            expected_prev = entry.hash
            expected_seq += 1
        else:
            verification = SealVerificationView(
                valid=expected_prev == seal.head_hash,
                checked=len(rows),
                reason=(
                    None
                    if expected_prev == seal.head_hash
                    else "seal_head_mismatch"
                ),
                head_matches=expected_prev == seal.head_hash,
                first_broken_seq=None,
            )

    return EvidenceSealDetailResponse(
        seal=_summary(seal, incident),
        entries=entries,
        seal_verification=verification,
        limitations=LIMITATIONS,
    )
