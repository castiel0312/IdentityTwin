"""Security Vaccination service.

Extracts behavioral attack signatures from confirmed attacks, manages the
PROPOSED -> ACTIVE -> REVOKED lifecycle under analyst authorization, and
evaluates active signatures against another merchant's observed behavior.

A vaccination match is an additional, explainable risk signal fed into the
existing deterministic risk engine. It never independently authorizes a payment
or bypasses the Trust Gateway, which remains the final enforcement boundary.

Signatures contain only normalized behavioral data: event sequences, feature
flags, risk indicators, and hashed identifiers. They never contain passwords,
access tokens, PayPal credentials, raw customer financial data, or unnecessary
PII.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    EntityNotFoundException,
    InsufficientPermissionsException,
    OwnershipMismatchException,
    PolicyViolationException,
)
from app.core.security import AuthenticatedPrincipal, RoleEnum
from app.db.repositories.twin_repo import TwinRepository
from app.evidence.hashchain import EvidenceChain
from app.models.event import SecurityEvent
from app.models.session import SessionRecord
from app.models.vaccination import VaccinationMatch, VaccinationSignature
from app.schemas.vaccination import (
    VaccinationAction,
    VaccinationEvaluateRequest,
    VaccinationMatchDetail,
    VaccinationSignatureActionRequest,
    VaccinationSignatureCreateRequest,
    VaccinationStatus,
)

# Minimum explainable match score (0-100) required before a signature is
# considered matched. A single generic indicator is never sufficient.
_MATCH_THRESHOLD = 60.0
# Risk points added to the session score when a signature matches.
_MATCH_RISK_POINTS = 25.0
# Events outside this window (seconds) are not part of a sequence match.
_SEQUENCE_WINDOW_SECONDS = 1800


class VaccinationService:
    """Server-side security vaccination lifecycle and matching."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ #
    # Signature extraction from a confirmed attack
    # ------------------------------------------------------------------ #
    def extract_signature_from_attack(
        self,
        session: SessionRecord,
        principal: AuthenticatedPrincipal,
        request: VaccinationSignatureCreateRequest,
    ) -> VaccinationSignature:
        """Build a PROPOSED signature from a confirmed attack session.

        The signature definition is derived from the session's persisted
        security events and the supplied behavioral pattern. It is normalized
        and sanitized: no secrets, tokens, or raw customer financial data.
        """
        if session.merchant_id != principal.merchant_id or session.user_id != principal.user_id:
            raise OwnershipMismatchException(
                message="Cannot extract a signature from a session outside the authenticated scope.",
                code="SESSION_SCOPE_MISMATCH",
            )

        events = self._session_events(session.session_id)
        definition = self._build_definition(events, request.signature_definition)

        signature = VaccinationSignature(
            source_merchant_id=session.merchant_id,
            version=1,
            status=VaccinationStatus.PROPOSED.value,
            name=request.name,
            description=request.description,
            signature_definition=definition,
            detection_confidence=request.detection_confidence,
            evidence_refs=list(request.evidence_refs),
            created_by=principal.user_id,
        )
        self.db.add(signature)
        self.db.flush()

        # Every lifecycle transition is auditable evidence.
        chain = EvidenceChain(self.db)
        chain.append(
            "vaccination_signature_created",
            {
                "type": "vaccination_signature_created",
                "signature_id": str(signature.signature_id),
                "source_merchant_id": str(session.merchant_id),
                "session_id": str(session.session_id),
                "status": signature.status,
                "name": signature.name,
                "pattern_hash": definition.get("signature_hash"),
                "detection_confidence": signature.detection_confidence,
                "evidence_refs": signature.evidence_refs,
                "created_by": str(principal.user_id),
                "plane": "real",
            },
        )
        self.db.commit()
        self.db.refresh(signature)
        return signature

    # ------------------------------------------------------------------ #
    # Lifecycle (analyst only)
    # ------------------------------------------------------------------ #
    def _require_analyst(self, principal: AuthenticatedPrincipal) -> None:
        if principal.role not in (RoleEnum.ANALYST, RoleEnum.ADMIN):
            raise InsufficientPermissionsException(
                message="Vaccination actions require analyst or admin credentials.",
                code="ANALYST_ROLE_REQUIRED",
            )

    def _get_signature(
        self, signature_id: UUID, principal: AuthenticatedPrincipal
    ) -> VaccinationSignature:
        signature = self.db.get(VaccinationSignature, signature_id)
        if not signature:
            raise EntityNotFoundException(
                message=f"Vaccination signature '{signature_id}' not found.",
                code="VACCINATION_SIGNATURE_NOT_FOUND",
            )
        # Tenant isolation: a merchant may only manage signatures it sourced.
        if signature.source_merchant_id != principal.merchant_id:
            raise OwnershipMismatchException(
                message="Signature belongs to a different merchant domain.",
                code="VACCINATION_SCOPE_MISMATCH",
            )
        return signature

    def _transition(
        self,
        signature: VaccinationSignature,
        new_status: str,
        action: str,
        principal: AuthenticatedPrincipal,
        notes: str | None,
    ) -> VaccinationSignature:
        previous = signature.status
        if previous == new_status:
            raise PolicyViolationException(
                message=f"Signature is already in '{new_status}' state.",
                code="VACCINATION_TERMINAL_STATE",
            )
        if (
            previous == VaccinationStatus.REVOKED.value
            and new_status != VaccinationStatus.REVOKED.value
        ):
            raise PolicyViolationException(
                message="A revoked signature cannot be re-activated.",
                code="VACCINATION_REVOKED_IMMUTABLE",
            )

        now = datetime.now(timezone.utc)
        signature.status = new_status
        signature.updated_at = now
        if action == VaccinationAction.APPROVE.value:
            signature.approved_by = principal.user_id
            signature.approved_at = now
        elif action == VaccinationAction.REVOKE.value:
            signature.revoked_by = principal.user_id
            signature.revoked_at = now

        chain = EvidenceChain(self.db)
        chain.append(
            f"vaccination_signature_{action}",
            {
                "type": f"vaccination_signature_{action}",
                "signature_id": str(signature.signature_id),
                "source_merchant_id": str(signature.source_merchant_id),
                "action": action,
                "previous_status": previous,
                "new_status": new_status,
                "analyst_id": str(principal.user_id),
                "notes": notes,
                "pattern_hash": signature.signature_definition.get("signature_hash"),
                "plane": "real",
            },
        )
        self.db.commit()
        self.db.refresh(signature)
        return signature

    def approve_signature(
        self,
        signature_id: UUID,
        principal: AuthenticatedPrincipal,
        request: VaccinationSignatureActionRequest,
    ) -> VaccinationSignature:
        """Approve a PROPOSED signature. Only ACTIVE signatures are applied."""
        self._require_analyst(principal)
        signature = self._get_signature(signature_id, principal)
        if signature.status != VaccinationStatus.PROPOSED.value:
            raise PolicyViolationException(
                message=f"Only PROPOSED signatures can be approved (current: {signature.status}).",
                code="VACCINATION_NOT_PROPOSED",
            )
        return self._transition(
            signature,
            VaccinationStatus.ACTIVE.value,
            VaccinationAction.APPROVE.value,
            principal,
            request.notes,
        )

    def reject_signature(
        self,
        signature_id: UUID,
        principal: AuthenticatedPrincipal,
        request: VaccinationSignatureActionRequest,
    ) -> VaccinationSignature:
        """Reject a PROPOSED signature (moves to REVOKED, never applied)."""
        self._require_analyst(principal)
        signature = self._get_signature(signature_id, principal)
        if signature.status != VaccinationStatus.PROPOSED.value:
            raise PolicyViolationException(
                message=f"Only PROPOSED signatures can be rejected (current: {signature.status}).",
                code="VACCINATION_NOT_PROPOSED",
            )
        return self._transition(
            signature,
            VaccinationStatus.REVOKED.value,
            VaccinationAction.REJECT.value,
            principal,
            request.notes,
        )

    def revoke_signature(
        self,
        signature_id: UUID,
        principal: AuthenticatedPrincipal,
        request: VaccinationSignatureActionRequest,
    ) -> VaccinationSignature:
        """Revoke an ACTIVE signature so it no longer matches."""
        self._require_analyst(principal)
        signature = self._get_signature(signature_id, principal)
        if signature.status != VaccinationStatus.ACTIVE.value:
            raise PolicyViolationException(
                message=f"Only ACTIVE signatures can be revoked (current: {signature.status}).",
                code="VACCINATION_NOT_ACTIVE",
            )
        return self._transition(
            signature,
            VaccinationStatus.REVOKED.value,
            VaccinationAction.REVOKE.value,
            principal,
            request.notes,
        )

    # ------------------------------------------------------------------ #
    # Listing / detail (tenant isolated)
    # ------------------------------------------------------------------ #
    def list_signatures(
        self,
        principal: AuthenticatedPrincipal,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[VaccinationSignature], int]:
        """List signatures sourced by the principal's merchant."""
        filters = [VaccinationSignature.source_merchant_id == principal.merchant_id]
        if status:
            filters.append(VaccinationSignature.status == status)

        from sqlalchemy import func

        total_stmt = select(func.count()).select_from(VaccinationSignature).where(*filters)
        total = self.db.scalar(total_stmt) or 0

        stmt = (
            select(VaccinationSignature)
            .where(*filters)
            .order_by(VaccinationSignature.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list(self.db.scalars(stmt).all())
        return items, total

    def get_signature(
        self, signature_id: UUID, principal: AuthenticatedPrincipal
    ) -> VaccinationSignature:
        return self._get_signature(signature_id, principal)

    # ------------------------------------------------------------------ #
    # Deterministic matching against active signatures
    # ------------------------------------------------------------------ #
    def evaluate(
        self,
        session: SessionRecord,
        principal: AuthenticatedPrincipal,
        request: VaccinationEvaluateRequest,
    ) -> VaccinationMatchDetail:
        """Evaluate a request against active signatures for the target merchant.

        Returns a match detail. When a match is found, a VaccinationMatch row
        is persisted and the match references the exact signature version.
        """
        if session.merchant_id != principal.merchant_id or session.user_id != principal.user_id:
            raise OwnershipMismatchException(
                message="Cannot evaluate events for a session outside the authenticated scope.",
                code="SESSION_SCOPE_MISMATCH",
            )

        active_signatures = self.db.scalars(
            select(VaccinationSignature).where(
                VaccinationSignature.status == VaccinationStatus.ACTIVE.value
            )
        ).all()

        events = self._session_events(session.session_id)
        best: VaccinationMatchDetail | None = None

        for signature in active_signatures:
            result = SignatureMatcher.match(
                signature_definition=signature.signature_definition,
                session_events=events,
                request=request,
                twin_repo=TwinRepository(self.db),
                merchant_id=session.merchant_id,
            )
            if not result["matched"]:
                continue
            detail = VaccinationMatchDetail(
                matched=True,
                signature_id=signature.signature_id,
                signature_name=signature.name,
                match_score=result["score"],
                match_reason=result["reason"],
                matched_features=result["matched_features"],
                evidence_refs=list(signature.evidence_refs),
                risk_points=result["risk_points"],
            )
            if best is None or detail.match_score > best.match_score:
                best = detail

        if best is not None:
            self._record_match(session, principal, best)
        return best or VaccinationMatchDetail(matched=False)

    def _record_match(
        self,
        session: SessionRecord,
        principal: AuthenticatedPrincipal,
        detail: VaccinationMatchDetail,
    ) -> None:
        match = VaccinationMatch(
            signature_id=detail.signature_id or uuid4(),
            target_merchant_id=session.merchant_id,
            session_id=session.session_id,
            match_score=detail.match_score,
            match_reason=detail.match_reason,
            matched_features=detail.matched_features,
            evidence_refs=detail.evidence_refs,
            risk_points=detail.risk_points,
        )
        self.db.add(match)
        self.db.flush()

        chain = EvidenceChain(self.db)
        chain.append(
            "vaccination_signature_matched",
            {
                "type": "vaccination_signature_matched",
                "signature_id": str(detail.signature_id or uuid4()),
                "signature_name": detail.signature_name,
                "target_merchant_id": str(session.merchant_id),
                "session_id": str(session.session_id),
                "match_score": detail.match_score,
                "match_reason": detail.match_reason,
                "matched_features": detail.matched_features,
                "risk_points": detail.risk_points,
                "evidence_refs": detail.evidence_refs,
                "plane": "real",
            },
        )
        self.db.commit()

    def list_matches(
        self,
        principal: AuthenticatedPrincipal,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[VaccinationMatch], int]:
        """List matches recorded for the principal's merchant (target scope)."""
        from sqlalchemy import func

        filters = [VaccinationMatch.target_merchant_id == principal.merchant_id]
        total_stmt = select(func.count()).select_from(VaccinationMatch).where(*filters)
        total = self.db.scalar(total_stmt) or 0
        stmt = (
            select(VaccinationMatch)
            .where(*filters)
            .order_by(VaccinationMatch.matched_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list(self.db.scalars(stmt).all())
        return items, total

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _session_events(self, session_id: UUID) -> list[dict[str, Any]]:
        stmt = (
            select(SecurityEvent)
            .where(SecurityEvent.session_id == session_id)
            .order_by(SecurityEvent.occurred_at.asc())
        )
        events: list[dict[str, Any]] = []
        for ev in self.db.scalars(stmt).all():
            events.append(
                {
                    "event_id": str(ev.event_id),
                    "event_type": ev.event_type,
                    "action": ev.action,
                    "amount": float((ev.metadata_payload or {}).get("amount", 0.0)),
                    "recipient": (ev.metadata_payload or {}).get("recipient_email", ""),
                    "device_id": ev.device_id,
                    "ip_address": ev.ip_address,
                    "occurred_at": ev.occurred_at,
                    "metadata": ev.metadata_payload or {},
                }
            )
        return events

    def _build_definition(
        self, events: list[dict[str, Any]], supplied: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a normalized, sanitized signature definition.

        Only behavioral fields are retained. PII, secrets, tokens, and raw
        customer financial data are excluded.
        """
        event_types = [e["event_type"] for e in events]
        actions = [e["action"] for e in events]
        devices = {e["device_id"] for e in events if e["device_id"]}
        locations = {e["ip_address"] for e in events if e["ip_address"]}
        amounts = [e["amount"] for e in events if isinstance(e["amount"], (int, float))]
        max_amount = max(amounts) if amounts else 0.0

        pattern = dict(supplied.get("pattern", {}))
        pattern.setdefault("action_type", actions[-1] if actions else "payout")
        pattern.setdefault("event_types_observed", sorted(set(event_types)))
        pattern.setdefault("actions_observed", sorted(set(actions)))
        pattern.setdefault("device_count", len(devices))
        pattern.setdefault("location_count", len(locations))
        pattern.setdefault("max_amount_observed", round(float(max_amount), 2))
        pattern.setdefault("event_count", len(events))
        pattern.setdefault("within_seconds", _SEQUENCE_WINDOW_SECONDS)

        definition = {
            "version": 1,
            "pattern": pattern,
            "risk_indicators": {
                "max_amount_observed": round(float(max_amount), 2),
                "event_count": len(events),
            },
            "detection_confidence": supplied.get("detection_confidence", 80.0),
            "evidence_refs": list(supplied.get("evidence_refs", [])),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        definition["signature_hash"] = self._definition_hash(definition)
        return definition

    @staticmethod
    def _definition_hash(definition: dict[str, Any]) -> str:
        import hashlib
        import json

        canonical = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()[:32]


class SignatureMatcher:
    """Deterministic, explainable matching of a request against a signature.

    A match requires the action type and the observed event sequence to agree
    with the signature pattern, plus at least one corroborating behavioral
    feature. A single generic indicator is never sufficient.
    """

    @staticmethod
    def match(
        *,
        signature_definition: dict[str, Any],
        session_events: list[dict[str, Any]],
        request: VaccinationEvaluateRequest,
        twin_repo: TwinRepository,
        merchant_id: UUID,
    ) -> dict[str, Any]:
        pattern = signature_definition.get("pattern", {}) if signature_definition else {}
        matched_features: dict[str, Any] = {}
        score = 0.0
        reasons: list[str] = []

        # 1. Action type must agree (mandatory).
        if pattern.get("action_type") and pattern["action_type"] != request.action_type:
            return {
                "matched": False,
                "score": 0.0,
                "reason": "action_type_mismatch",
                "matched_features": {},
                "risk_points": 0.0,
            }
        reasons.append("action_type_agreed")
        score += 20.0
        matched_features["action_type"] = request.action_type

        # 2. Event sequence must be present in the session (mandatory).
        sequence = pattern.get("event_sequence", [])
        sequence_matched = SignatureMatcher._match_sequence(
            session_events, sequence, pattern.get("within_seconds", _SEQUENCE_WINDOW_SECONDS)
        )
        if sequence and not sequence_matched:
            return {
                "matched": False,
                "score": score,
                "reason": "event_sequence_not_present",
                "matched_features": matched_features,
                "risk_points": 0.0,
            }
        if sequence:
            reasons.append("event_sequence_present")
            score += 30.0
            matched_features["event_sequence"] = sequence

        # 3. Corroborating behavioral features (each adds to confidence).
        twin = twin_repo.get_twin(merchant_id, request.session_id)
        snapshot = twin_repo.to_snapshot(twin) if twin else None

        device_new = SignatureMatcher._is_new(request, snapshot, "device", session_events)
        location_new = SignatureMatcher._is_new(request, snapshot, "location", session_events)
        payee_new = SignatureMatcher._is_new(request, snapshot, "payee", session_events)

        if pattern.get("requires_new_device") and device_new:
            reasons.append("new_device")
            score += 15.0
            matched_features["new_device"] = True
        if pattern.get("requires_new_location") and location_new:
            reasons.append("new_location")
            score += 10.0
            matched_features["new_location"] = True
        if pattern.get("requires_new_payee") and payee_new:
            reasons.append("new_payee")
            score += 15.0
            matched_features["new_payee"] = True

        # Amount threshold (large payout characteristic).
        amount_threshold = pattern.get("amount_threshold")
        if amount_threshold is not None and request.amount >= float(amount_threshold):
            reasons.append("large_payout")
            score += 10.0
            matched_features["large_payout"] = True

        matched = score >= _MATCH_THRESHOLD
        risk_points = _MATCH_RISK_POINTS if matched else 0.0
        return {
            "matched": matched,
            "score": round(min(100.0, score), 2),
            "reason": "; ".join(reasons) if reasons else "no_match",
            "matched_features": matched_features,
            "risk_points": risk_points,
        }

    @staticmethod
    def _match_sequence(
        events: list[dict[str, Any]],
        sequence: list[dict[str, Any]],
        window_seconds: int,
    ) -> bool:
        if not sequence:
            return True
        if not events:
            return False
        # Ordered subsequence match within the time window.
        seq_idx = 0
        first_time = None
        for ev in events:
            step = sequence[seq_idx]
            if ev["event_type"] == step.get("event_type") or ev["action"] == step.get(
                "action_type"
            ):
                if first_time is None:
                    first_time = ev["occurred_at"]
                seq_idx += 1
                if seq_idx >= len(sequence):
                    break
        if seq_idx < len(sequence):
            return False
        # Window check: first and last matched event within window.
        if first_time is not None and events:
            last_time = events[-1]["occurred_at"]
            delta = abs((last_time - first_time).total_seconds())
            return delta <= window_seconds
        return True

    @staticmethod
    def _is_new(
        request: VaccinationEvaluateRequest,
        snapshot: Any,
        dimension: str,
        session_events: list[dict[str, Any]],
    ) -> bool:
        """Whether the request's dimension value is unknown to the merchant twin."""
        if dimension == "device":
            known = set((snapshot or {}).confirmed_devices or []) if snapshot else set()
            recent_devices = {e["device_id"] for e in session_events if e["device_id"]}
            # A device is "new" if it appears in session events but is not a confirmed baseline device.
            return bool(recent_devices - known)
        if dimension == "location":
            known = set((snapshot or {}).confirmed_locations or []) if snapshot else set()
            recent_locations = {e["ip_address"] for e in session_events if e["ip_address"]}
            return bool(recent_locations - known)
        if dimension == "payee":
            known = set((snapshot or {}).confirmed_payees(2) or []) if snapshot else set()
            recent_payees = {e["recipient"] for e in session_events if e["recipient"]}
            return bool(recent_payees - known)
        return False
