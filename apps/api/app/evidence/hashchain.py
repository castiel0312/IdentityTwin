import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.evidence import (
    EvidenceChainHead,
    EvidenceLogEntry,
    EvidencePayload,
    IncidentSeal,
)
from app.models.incident import IncidentRecord
from app.models.session import SessionRecord

GENESIS_PREV_HASH = "0" * 64
_APPEND_LOCK = threading.RLock()


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_hash(payload: dict[str, Any]) -> str:
    c = canonical_json(payload).encode("utf-8")
    return hashlib.sha256(c).hexdigest()


def compute_hash(seq: int, event_ref: str, p_hash: str, prev_hash: str) -> str:
    m = hashlib.sha256()
    m.update(str(seq).encode("utf-8"))
    m.update(b"|")
    m.update((event_ref or "").encode("utf-8"))
    m.update(b"|")
    m.update((p_hash or "").encode("utf-8"))
    m.update(b"|")
    m.update((prev_hash or "").encode("utf-8"))
    return m.hexdigest()


class EvidenceChain:
    def __init__(self, db: Session):
        self.db = db

    def head(self) -> tuple[str, int] | None:
        checkpoint = self.db.get(EvidenceChainHead, 1)
        if checkpoint is None or checkpoint.seq == 0:
            return None
        return checkpoint.hash, checkpoint.seq

    def append(self, event_ref: str, payload: dict[str, Any]) -> dict[str, Any]:
        p_hash = payload_hash(payload)
        session_id = payload.get("session_id")
        event_type = payload.get("type", event_ref)
        session_uuid: UUID | None = None
        if session_id:
            try:
                session_uuid = UUID(str(session_id))
            except ValueError:
                session_uuid = None
        merchant_uuid: UUID | None = None
        raw_merchant = payload.get("merchant_id")
        if raw_merchant:
            try:
                merchant_uuid = UUID(str(raw_merchant))
            except ValueError:
                merchant_uuid = None
        if merchant_uuid is None and session_uuid is not None:
            scoped_session = self.db.get(SessionRecord, session_uuid)
            if scoped_session is not None:
                merchant_uuid = scoped_session.merchant_id
        if (
            session_uuid is not None
            and event_type not in {"incident_sealed", "analyst_action"}
            and self.db.scalars(
                select(IncidentSeal).where(IncidentSeal.session_id == session_uuid)
            ).first()
        ):
            raise ValueError("Evidence for a sealed session must be recorded separately.")

        # The process lock covers SQLite and the transaction advisory lock
        # serializes writers across API workers on PostgreSQL.
        with _APPEND_LOCK:
            if self.db.get_bind().dialect.name == "postgresql":
                self.db.execute(text("SELECT pg_advisory_xact_lock(123456789, 42)"))

            checkpoint = self.db.get(EvidenceChainHead, 1)
            if checkpoint is None:
                checkpoint = EvidenceChainHead(id=1, seq=0, hash=GENESIS_PREV_HASH)
                self.db.add(checkpoint)
                self.db.flush()

            prev_hash = checkpoint.hash
            seq = checkpoint.seq + 1
            h = compute_hash(seq, event_ref, p_hash, prev_hash)
            entry = EvidenceLogEntry(
                seq=seq,
                event_ref=event_ref,
                payload_hash=p_hash,
                prev_hash=prev_hash,
                hash=h,
                session_id=session_uuid,
                merchant_id=merchant_uuid,
                created_at=datetime.now(timezone.utc),
            )
            self.db.add(entry)
            payload_row = EvidencePayload(seq=seq, payload=payload)
            self.db.add(payload_row)
            checkpoint.seq = seq
            checkpoint.hash = h
            self.db.commit()
            self.db.refresh(entry)
            return {"seq": entry.seq, "hash": entry.hash}

    def verify(self) -> dict[str, Any]:
        stmt = select(EvidenceLogEntry).order_by(EvidenceLogEntry.seq.asc())
        entries = list(self.db.scalars(stmt).all())
        checkpoint = self.db.get(EvidenceChainHead, 1)
        reported_head = entries[-1].hash if entries else GENESIS_PREV_HASH

        if checkpoint is None:
            return {
                "valid": not entries,
                "checked": 0,
                "head_hash": reported_head,
                **(
                    {"first_broken_seq": entries[0].seq, "reason": "checkpoint_missing"}
                    if entries
                    else {}
                ),
            }

        prev_hash = GENESIS_PREV_HASH
        for expected_seq, e in enumerate(entries, start=1):
            if e.seq != expected_seq:
                return {
                    "valid": False,
                    "checked": expected_seq - 1,
                    "head_hash": reported_head,
                    "first_broken_seq": expected_seq,
                    "reason": "sequence_gap",
                }
            if e.prev_hash != prev_hash:
                return {
                    "valid": False,
                    "checked": expected_seq - 1,
                    "head_hash": reported_head,
                    "first_broken_seq": e.seq,
                    "reason": "prev_hash_mismatch",
                }

            payload = self.db.get(EvidencePayload, e.seq)
            if payload is None or payload_hash(payload.payload) != e.payload_hash:
                return {
                    "valid": False,
                    "checked": e.seq - 1,
                    "head_hash": reported_head,
                    "first_broken_seq": e.seq,
                    "reason": "payload_hash_mismatch",
                }
            expected = compute_hash(e.seq, e.event_ref, e.payload_hash, e.prev_hash)
            if expected != e.hash:
                return {
                    "valid": False,
                    "checked": e.seq - 1,
                    "head_hash": reported_head,
                    "first_broken_seq": e.seq,
                    "reason": "hash_mismatch",
                }
            prev_hash = e.hash

        if checkpoint.seq != len(entries) or checkpoint.hash != prev_hash:
            broken_seq = min(checkpoint.seq, len(entries)) + 1
            return {
                "valid": False,
                "checked": len(entries),
                "head_hash": reported_head,
                "first_broken_seq": broken_seq,
                "reason": "head_checkpoint_mismatch",
            }

        payload_count = self.db.scalar(select(func.count()).select_from(EvidencePayload)) or 0
        if payload_count != len(entries):
            return {
                "valid": False,
                "checked": len(entries),
                "head_hash": reported_head,
                "first_broken_seq": len(entries) + 1,
                "reason": "orphaned_payload",
            }

        return {"valid": True, "checked": len(entries), "head_hash": prev_hash}

    def seal(
        self,
        incident_id: UUID | str,
        session_id: UUID | str,
        merchant_id: UUID | str,
    ) -> dict[str, Any]:
        incident_uuid = UUID(str(incident_id))
        session_uuid = UUID(str(session_id))
        merchant_uuid = UUID(str(merchant_id))
        incident = self.db.get(IncidentRecord, incident_uuid)
        session = self.db.get(SessionRecord, session_uuid)
        if (
            incident is None
            or session is None
            or incident.session_id != session_uuid
            or incident.merchant_id != merchant_uuid
            or session.merchant_id != merchant_uuid
        ):
            raise ValueError("Evidence seal must match the incident, session and merchant.")

        existing = self.db.scalars(
            select(IncidentSeal).where(IncidentSeal.incident_id == incident_uuid)
        ).first()
        if existing:
            if existing.session_id != session_uuid or existing.merchant_id != merchant_uuid:
                raise ValueError("Existing evidence seal belongs to a different tenant scope.")
            return {
                "seal_id": str(existing.seal_id),
                "incident_id": str(existing.incident_id),
                "start_seq": existing.start_seq,
                "end_seq": existing.end_seq,
                "head_hash": existing.head_hash,
            }

        self.append(
            "incident_sealed",
            {
                "type": "incident_sealed",
                "incident_id": str(incident_uuid),
                "session_id": str(session_uuid),
            },
        )

        scoped_sequences = list(
            self.db.scalars(
                select(EvidenceLogEntry.seq)
                .where(
                    EvidenceLogEntry.session_id == session_uuid,
                    EvidenceLogEntry.merchant_id == merchant_uuid,
                )
                .order_by(EvidenceLogEntry.seq.asc())
            ).all()
        )

        start_seq = min(scoped_sequences) if scoped_sequences else 0
        end_seq = max(scoped_sequences) if scoped_sequences else 0
        end_entry = self.db.get(EvidenceLogEntry, end_seq) if end_seq else None
        head_hash = end_entry.hash if end_entry else GENESIS_PREV_HASH
        seal = IncidentSeal(
            incident_id=incident_uuid,
            session_id=session_uuid,
            merchant_id=UUID(str(merchant_id)),
            start_seq=start_seq,
            end_seq=end_seq,
            head_hash=head_hash,
        )
        self.db.add(seal)
        incident.sealed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(seal)
        return {
            "seal_id": str(seal.seal_id),
            "incident_id": str(seal.incident_id),
            "start_seq": seal.start_seq,
            "end_seq": seal.end_seq,
            "head_hash": seal.head_hash,
        }
