"""Deterministic, merchant-scoped evidence extraction and redaction.

The LLM (when enabled) only ever receives an explicit allowlisted projection
built by this module. Arbitrary incident summaries, event metadata and other
free-text fields are never forwarded because they cannot be proven PII-free by
regular expressions alone.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException
from app.core.security import AuthenticatedPrincipal
from app.models.canary import CanaryRecord
from app.models.event import SecurityEvent
from app.models.evidence import EvidenceLogEntry, EvidencePayload, IncidentSeal
from app.models.incident import IncidentRecord
from app.models.payout import PayoutRequestRecord
from app.models.risk import RiskDecisionRecord
from app.models.session import SessionRecord

MAX_TEXT = 280
MAX_CODE_TEXT = 96
MAX_LIST_ITEMS = 200

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SECRET_RE = re.compile(
    r"(?i)\b(?:sk|pk|rk|ghp|gho|ghs|ghu|xox[abps]|akia|asia)[-_a-z0-9]{8,}\b"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_LONG_NUMBER_RE = re.compile(r"\b(?:\d[ -]?){12,19}\b")
_SHORT_NUMBER_RE = re.compile(r"\b\d{6,11}\b")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+\d[\d ()-]{6,}\d|\(?\d{3}\)?[ -]\d{3}[ -]\d{4})(?!\d)"
)
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IPV6_RE = re.compile(
    r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{1,4}(?![\w:.])"
)
_STREET_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z0-9][A-Za-z0-9'.-]*\s+){0,5}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|"
    r"Way|Place|Pl|Terrace|Ter|Circle|Cir|Highway|Hwy|Parkway|Pkwy)\.?\b",
    re.IGNORECASE,
)
_NAME_LABEL_RE = re.compile(
    r"(?i)\b(?:full[_\s-]?name|first[_\s-]?name|last[_\s-]?name|"
    r"customer[_\s-]?name|recipient[_\s-]?name|payee[_\s-]?name|name)"
    r"\s*[:=]\s*[A-Za-z][A-Za-z'.-]*(?:\s+[A-Za-z][A-Za-z'.-]*){0,3}"
)
_NAME_RE = re.compile(r"\b[A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){1,2}\b")
_SAFE_CODE_RE = re.compile(r"[^A-Za-z0-9_.:-]+")

_FORBIDDEN_LLM_KEYS = frozenset(
    {
        "account",
        "account_number",
        "address",
        "card",
        "card_number",
        "customer_name",
        "cvv",
        "description",
        "device_id",
        "email",
        "evidence_summary",
        "first_name",
        "full_name",
        "iban",
        "ip_address",
        "last_name",
        "matched_in",
        "metadata",
        "name",
        "note",
        "password",
        "phone",
        "recipient",
        "recipient_email",
        "routing_number",
        "secret",
        "secret_value",
        "ssn",
        "tag",
        "title",
        "token",
    }
)

_ALLOWED_TOP_LEVEL = frozenset(
    {
        "incident",
        "session",
        "events",
        "risk_decisions",
        "payouts",
        "evidence_chain",
        "canaries",
        "seal",
    }
)

_ALLOWED_KEYS = {
    "incident": frozenset(
        {
            "incident_id",
            "severity",
            "status",
            "risk_score",
            "trigger_reason",
            "sealed_at",
        }
    ),
    "session": frozenset({"session_id", "status", "trust_level", "risk_score"}),
    "event": frozenset({"event_type", "action", "occurred_at"}),
    "risk_decision": frozenset(
        {
            "decision_id",
            "risk_score",
            "trust_level",
            "action",
            "routing_destination",
            "reason_codes",
            "risk_signals",
        }
    ),
    "payout": frozenset({"payout_id", "amount", "currency", "status", "provider_name"}),
    "evidence_chain": frozenset({"seq", "event_ref", "type", "hash"}),
    "canary": frozenset({"kind", "armed", "triggered_at"}),
    "seal": frozenset({"seal_id", "start_seq", "end_seq", "head_hash"}),
}


def _redact_ip_candidates(pattern: re.Pattern[str], text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        candidate = match.group(0)
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            return candidate
        return "[REDACTED_IP]"

    return pattern.sub(_replace, text)


def _scrub_hard_identifiers(text: str) -> str:
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _SECRET_RE.sub("[REDACTED_SECRET]", text)
    text = _BEARER_RE.sub("[REDACTED_SECRET]", text)
    text = _JWT_RE.sub("[REDACTED_SECRET]", text)
    text = _SSN_RE.sub("[REDACTED_SSN]", text)
    text = _LONG_NUMBER_RE.sub("[REDACTED_NUMBER]", text)
    text = _redact_ip_candidates(_IPV4_RE, text)
    text = _redact_ip_candidates(_IPV6_RE, text)
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = _SHORT_NUMBER_RE.sub("[REDACTED_NUMBER]", text)
    return text


def scrub_text(value: Any) -> str:
    """Deterministically remove likely PII/financial identifiers from free text.

    This is best-effort defence for free text. The LLM projection never relies
    on it alone: free-text incident summaries, titles, descriptions and event
    metadata are excluded structurally instead of being sent through regexes.
    """
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = _scrub_hard_identifiers(text)
    text = _STREET_RE.sub("[REDACTED_ADDRESS]", text)
    text = _NAME_LABEL_RE.sub("[REDACTED_NAME]", text)
    text = _NAME_RE.sub("[REDACTED_NAME]", text)
    return text


def safe_text(value: Any, *, limit: int = MAX_TEXT) -> str:
    """Bound an internally generated string without name/address heuristics."""
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return _scrub_hard_identifiers(text)[:limit]


def clean_code(value: Any, *, limit: int = MAX_CODE_TEXT) -> str:
    """Normalize an internal code/enum so free text or prompt payloads cannot pass."""
    if value is None:
        return ""
    text = _scrub_hard_identifiers(str(value).strip())
    return _SAFE_CODE_RE.sub("_", text).strip("_")[:limit]


def scrub_structure(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {key: scrub_structure(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_structure(item, depth=depth + 1) for item in value[:MAX_LIST_ITEMS]]
    if isinstance(value, str):
        return scrub_text(value)
    return value


def as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = as_utc(value)
    return normalized.isoformat() if normalized is not None else None


@dataclass
class ExtractedEvidence:
    incident: IncidentRecord
    session: SessionRecord | None
    events: list[SecurityEvent] = field(default_factory=list)
    decisions: list[RiskDecisionRecord] = field(default_factory=list)
    payouts: list[PayoutRequestRecord] = field(default_factory=list)
    chain_entries: list[tuple[EvidenceLogEntry, dict[str, Any]]] = field(default_factory=list)
    canaries: list[CanaryRecord] = field(default_factory=list)
    seal: IncidentSeal | None = None


@dataclass(frozen=True)
class LlmEvidenceProjection:
    """Allowlisted, redacted evidence that may be sent to an external LLM."""

    payload: dict[str, Any]
    redaction_applied: bool
    excluded_categories: tuple[str, ...]


def ensure_incident_access(
    db: Session,
    principal: AuthenticatedPrincipal,
    incident_id: UUID,
) -> IncidentRecord:
    incident = db.get(IncidentRecord, incident_id)
    if incident is None or incident.merchant_id != principal.merchant_id:
        raise EntityNotFoundException(
            message="Incident not found.", code="INCIDENT_NOT_FOUND"
        )
    return incident


def extract_evidence(
    db: Session,
    principal: AuthenticatedPrincipal,
    incident_id: UUID,
    *,
    max_events: int = 100,
) -> ExtractedEvidence:
    """Load evidence for one incident, scoped to the authenticated merchant.

    Cross-tenant incidents return 404 rather than revealing that they exist.
    This function performs no writes.
    """
    incident = ensure_incident_access(db, principal, incident_id)

    session = (
        db.get(SessionRecord, incident.session_id) if incident.session_id else None
    )
    if session is not None and session.merchant_id != principal.merchant_id:
        session = None

    events: list[SecurityEvent] = []
    decisions: list[RiskDecisionRecord] = []
    payouts: list[PayoutRequestRecord] = []
    chain_entries: list[tuple[EvidenceLogEntry, dict[str, Any]]] = []
    canaries: list[CanaryRecord] = []

    if incident.session_id is not None:
        events = list(
            db.scalars(
                select(SecurityEvent)
                .where(
                    SecurityEvent.session_id == incident.session_id,
                    SecurityEvent.merchant_id == principal.merchant_id,
                )
                .order_by(SecurityEvent.occurred_at.asc())
                .limit(max_events)
            ).all()
        )
        decisions = list(
            db.scalars(
                select(RiskDecisionRecord)
                .where(
                    RiskDecisionRecord.session_id == incident.session_id,
                    RiskDecisionRecord.merchant_id == principal.merchant_id,
                )
                .order_by(RiskDecisionRecord.evaluated_at.asc())
                .limit(max_events)
            ).all()
        )
        payouts = list(
            db.scalars(
                select(PayoutRequestRecord)
                .where(
                    PayoutRequestRecord.session_id == incident.session_id,
                    PayoutRequestRecord.merchant_id == principal.merchant_id,
                )
                .order_by(PayoutRequestRecord.created_at.asc())
                .limit(max_events)
            ).all()
        )
        canaries = list(
            db.scalars(
                select(CanaryRecord)
                .where(
                    CanaryRecord.session_id == incident.session_id,
                    CanaryRecord.merchant_id == principal.merchant_id,
                )
                .order_by(CanaryRecord.kind.asc())
                .limit(max_events)
            ).all()
        )
        chain_limit = max(max_events, 200)
        rows = db.execute(
            select(EvidenceLogEntry, EvidencePayload)
            .join(EvidencePayload, EvidencePayload.seq == EvidenceLogEntry.seq)
            .where(
                EvidenceLogEntry.session_id == incident.session_id,
                EvidenceLogEntry.merchant_id == principal.merchant_id,
            )
            .order_by(EvidenceLogEntry.seq.asc())
            .limit(chain_limit)
        ).all()
        chain_entries = [(entry, dict(payload.payload or {})) for entry, payload in rows]

    seal = db.scalars(
        select(IncidentSeal)
        .where(
            IncidentSeal.incident_id == incident.incident_id,
            IncidentSeal.merchant_id == principal.merchant_id,
        )
        .order_by(IncidentSeal.sealed_at.desc())
    ).first()

    return ExtractedEvidence(
        incident=incident,
        session=session,
        events=events,
        decisions=decisions,
        payouts=payouts,
        chain_entries=chain_entries,
        canaries=canaries,
        seal=seal,
    )


def _numeric_signals(signals: dict[str, Any] | None) -> dict[str, float]:
    safe: dict[str, float] = {}
    for name, points in list((signals or {}).items())[:20]:
        if isinstance(points, bool) or not isinstance(points, (int, float)):
            continue
        safe[clean_code(name, limit=64)] = float(points)
    return safe


def _projection_incident(incident: IncidentRecord) -> dict[str, Any]:
    return {
        "incident_id": str(incident.incident_id),
        "severity": clean_code(incident.severity, limit=32),
        "status": clean_code(incident.status, limit=32),
        "risk_score": float(incident.risk_score),
        "trigger_reason": clean_code(incident.trigger_reason, limit=64),
        "sealed_at": _iso(incident.sealed_at),
    }


def _projection_session(session: SessionRecord | None) -> dict[str, Any] | None:
    if session is None:
        return None
    return {
        "session_id": str(session.session_id),
        "status": clean_code(session.status, limit=32),
        "trust_level": clean_code(session.trust_level, limit=32),
        "risk_score": float(session.risk_score),
    }


def compact_evidence(evidence: ExtractedEvidence) -> LlmEvidenceProjection:
    """Build the only payload that may be sent to an optional LLM call.

    Free-text incident summaries, titles, descriptions, event metadata and
    arbitrary chain payloads are excluded by construction. Values that are
    included are enum/code-like or numeric, and every string is normalized.
    """
    payload: dict[str, Any] = {
        "incident": _projection_incident(evidence.incident),
        "session": _projection_session(evidence.session),
        "events": [
            {
                "event_type": clean_code(event.event_type, limit=64),
                "action": clean_code(event.action, limit=64),
                "occurred_at": _iso(event.occurred_at),
            }
            for event in evidence.events[:40]
        ],
        "risk_decisions": [
            {
                "decision_id": str(decision.decision_id),
                "risk_score": float(decision.risk_score),
                "trust_level": clean_code(decision.trust_level, limit=32),
                "action": clean_code(decision.action, limit=64),
                "routing_destination": clean_code(decision.routing_destination, limit=64),
                "reason_codes": [
                    clean_code(code, limit=64) for code in (decision.reason_codes or [])[:20]
                ],
                "risk_signals": _numeric_signals(decision.risk_signals),
            }
            for decision in evidence.decisions[:40]
        ],
        "payouts": [
            {
                "payout_id": str(payout.payout_id),
                "amount": float(payout.amount),
                "currency": clean_code(payout.currency, limit=8),
                "status": clean_code(payout.status, limit=32),
                "provider_name": clean_code(payout.provider_name, limit=64),
            }
            for payout in evidence.payouts[:40]
        ],
        "evidence_chain": [
            {
                "seq": int(entry.seq),
                "event_ref": clean_code(entry.event_ref, limit=64),
                "type": clean_code(payload_row.get("type"), limit=64),
                "hash": clean_code(entry.hash, limit=64),
            }
            for entry, payload_row in evidence.chain_entries[:80]
        ],
        "canaries": [
            {
                "kind": clean_code(canary.kind, limit=32),
                "armed": bool(canary.armed),
                "triggered_at": _iso(canary.triggered_at),
            }
            for canary in evidence.canaries[:40]
        ],
        "seal": (
            {
                "seal_id": str(evidence.seal.seal_id),
                "start_seq": int(evidence.seal.start_seq),
                "end_seq": int(evidence.seal.end_seq),
                "head_hash": clean_code(evidence.seal.head_hash, limit=64),
            }
            if evidence.seal
            else None
        ),
    }
    excluded = (
        "incident.evidence_summary",
        "incident.title",
        "incident.description",
        "event.metadata",
        "event.ip_address",
        "event.device_id",
        "payout.recipient_email",
        "canary.tag",
        "evidence_chain.payload",
    )
    return LlmEvidenceProjection(
        payload=payload,
        redaction_applied=verify_llm_projection(payload),
        excluded_categories=excluded,
    )


def _verify_string(value: Any, *, max_length: int = 256) -> bool:
    return isinstance(value, str) and len(value) <= max_length


def _verify_keys(value: Any, allowed: frozenset[str]) -> bool:
    return isinstance(value, dict) and set(value).issubset(allowed)


def verify_llm_projection(payload: Any) -> bool:
    """Fail closed unless the payload matches the explicit projection allowlist."""
    if not isinstance(payload, dict) or not set(payload).issubset(_ALLOWED_TOP_LEVEL):
        return False
    if not isinstance(payload.get("incident"), dict):
        return False
    if not _verify_keys(payload["incident"], _ALLOWED_KEYS["incident"]):
        return False
    if not _verify_string(payload["incident"].get("incident_id")):
        return False

    session = payload.get("session")
    if session is not None:
        if not _verify_keys(session, _ALLOWED_KEYS["session"]):
            return False
        if not _verify_string(session.get("session_id")):
            return False

    for key in ("events", "risk_decisions", "payouts", "evidence_chain", "canaries"):
        if not isinstance(payload.get(key), list):
            return False

    for event in payload["events"]:
        if not _verify_keys(event, _ALLOWED_KEYS["event"]):
            return False
    for decision in payload["risk_decisions"]:
        if not _verify_keys(decision, _ALLOWED_KEYS["risk_decision"]):
            return False
        signals = decision.get("risk_signals")
        if not isinstance(signals, dict):
            return False
        if not all(
            isinstance(name, str) and isinstance(points, (int, float))
            for name, points in signals.items()
        ):
            return False
    for payout in payload["payouts"]:
        if not _verify_keys(payout, _ALLOWED_KEYS["payout"]):
            return False
    for entry in payload["evidence_chain"]:
        if not _verify_keys(entry, _ALLOWED_KEYS["evidence_chain"]):
            return False
    for canary in payload["canaries"]:
        if not _verify_keys(canary, _ALLOWED_KEYS["canary"]):
            return False

    seal = payload.get("seal")
    if seal is not None and not _verify_keys(seal, _ALLOWED_KEYS["seal"]):
        return False

    def _walk(value: Any, depth: int = 0) -> bool:
        if depth > 8:
            return False
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in _FORBIDDEN_LLM_KEYS:
                    return False
                if not _walk(item, depth=depth + 1):
                    return False
            return True
        if isinstance(value, list):
            return len(value) <= MAX_LIST_ITEMS and all(
                _walk(item, depth=depth + 1) for item in value
            )
        if isinstance(value, str):
            return len(value) <= 256
        return value is None or isinstance(value, (bool, int, float))

    return _walk(payload)
