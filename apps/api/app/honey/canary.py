import hashlib
import hmac
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.secrets import get_canary_hmac_secret
from app.core.security import AuthenticatedPrincipal
from app.evidence.hashchain import EvidenceChain
from app.models.canary import CanaryRecord
from app.models.session import SessionRecord

_ISSUE_LOCK = threading.RLock()
_CANARY_KINDS = (
    "api_credential",
    "customer_record",
    "invoice_export",
    "honey_endpoint",
    "honey_account",
)


def _string_values(value: Any, depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values = []
        for key, item in list(value.items())[:100]:
            values.extend(_string_values(key, depth + 1))
            values.extend(_string_values(item, depth + 1))
        return values
    if isinstance(value, list):
        values = []
        for item in value[:100]:
            values.extend(_string_values(item, depth + 1))
        return values
    return []


class CanaryRegistryService:
    def __init__(self, db: Session):
        self.db = db
        self.secret = get_canary_hmac_secret()

    def _derive_tag(self, session_id: str, kind: str, counter: int) -> tuple[str, str]:
        msg = f"{session_id}:{kind}:{counter}".encode()
        digest = hmac.new(self.secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]
        tag = (
            f"CRED-{digest[:8].upper()}"
            if kind == "api_credential"
            else f"CAN-{digest[:10].upper()}"
        )
        secret_value = digest
        return tag, secret_value

    def issue(
        self, session_id: str, identity_id: str | None = None, merchant_id: str | None = None
    ) -> list[dict[str, Any]]:
        session_uuid = uuid.UUID(session_id)
        if identity_id is None or merchant_id is None:
            raise ValueError("Canary issuance requires an owned session, identity and merchant.")
        identity_uuid = uuid.UUID(identity_id)
        merchant_uuid = uuid.UUID(merchant_id)
        session = self.db.get(SessionRecord, session_uuid)
        if (
            session is None
            or session.user_id != identity_uuid
            or session.merchant_id != merchant_uuid
        ):
            raise ValueError("Canary issuance requires an owned session, identity and merchant.")
        with _ISSUE_LOCK:
            if self.db.get_bind().dialect.name == "postgresql":
                self.db.execute(text("SELECT pg_advisory_xact_lock(123456789, 44)"))

            records = list(
                self.db.scalars(
                    select(CanaryRecord).where(CanaryRecord.session_id == session_uuid)
                ).all()
            )
            by_kind = {record.kind: record for record in records}
            for record in records:
                if identity_uuid is not None and record.identity_id not in (None, identity_uuid):
                    raise ValueError("Canary session is already bound to another identity.")
                if merchant_uuid is not None and record.merchant_id not in (None, merchant_uuid):
                    raise ValueError("Canary session is already bound to another merchant.")
                record.identity_id = identity_uuid
                record.merchant_id = merchant_uuid

            for counter, kind in enumerate(_CANARY_KINDS):
                if kind in by_kind:
                    continue
                tag, secret_value = self._derive_tag(str(session_uuid), kind, counter)
                record = CanaryRecord(
                    session_id=session_uuid,
                    identity_id=identity_uuid,
                    merchant_id=merchant_uuid,
                    kind=kind,
                    tag=tag,
                    secret_value=secret_value,
                    armed=True,
                    trigger_meta={},
                )
                self.db.add(record)
                by_kind[kind] = record

            self.db.commit()
            return [
                {
                    "canary_id": str(by_kind[kind].canary_id),
                    "kind": kind,
                    "tag": by_kind[kind].tag,
                    "secret_value": by_kind[kind].secret_value,
                }
                for kind in _CANARY_KINDS
            ]

    def check(
        self,
        observation: Any,
        principal: AuthenticatedPrincipal | None = None,
    ) -> dict[str, Any] | None:
        # observation can be dict with various fields
        candidates = []
        if isinstance(observation, dict):
            for key in [
                "authorization",
                "token",
                "api_key",
                "secret",
                "canary_token",
                "canary_id",
                "tag",
                "value",
            ]:
                v = observation.get(key)
                if isinstance(v, str) and v:
                    candidates.append(v)
            # check headers-like
            headers = observation.get("headers") or {}
            if isinstance(headers, dict):
                for k in ["authorization", "x-api-key"]:
                    v = headers.get(k) or headers.get(k.title()) or headers.get(k.upper())
                    if isinstance(v, str):
                        candidates.append(v)
            # check body
            body = observation.get("body") or {}
            candidates.extend(_string_values(body))
            # check path/query
            for k in ["path", "query", "recipient", "payee"]:
                v = observation.get(k)
                if isinstance(v, str):
                    candidates.append(v)
        elif isinstance(observation, str):
            candidates.append(observation)

        # Try to match by secret_value/tag
        for c in candidates:
            c_clean = c.strip()
            # strip bearer
            if c_clean.lower().startswith("bearer "):
                c_clean = c_clean[7:].strip()
            stmt = select(CanaryRecord).where(
                (CanaryRecord.secret_value == c_clean) | (CanaryRecord.tag == c_clean)
            )
            rec = self.db.scalars(stmt).first()
            if rec and rec.armed:
                obs_sid = observation.get("session_id") if isinstance(observation, dict) else None
                obs_merchant = (
                    observation.get("merchant_id") if isinstance(observation, dict) else None
                )
                obs_identity = (
                    observation.get("identity_id") if isinstance(observation, dict) else None
                )
                try:
                    same_session = rec.session_id == uuid.UUID(str(obs_sid))
                    same_merchant = rec.merchant_id == uuid.UUID(str(obs_merchant))
                    same_identity = rec.identity_id == uuid.UUID(str(obs_identity))
                except (TypeError, ValueError):
                    continue
                if not (same_session and same_merchant and same_identity):
                    # Cross-session/merchant/identity reuse detected
                    # Log security event but do NOT disarm the canary or return a hit
                    # This prevents an attacker from using their canary to isolate a victim session
                    if principal is not None:
                        self._log_cross_session_reuse(rec, observation, principal)
                    continue
                rec.armed = False
                rec.triggered_at = datetime.now(timezone.utc)
                rec.trigger_meta = {
                    "matched_in": observation.get("matched_in")
                    if isinstance(observation, dict)
                    else "unknown",
                    "cross_session_reuse": False,
                }
                self.db.commit()
                return {
                    "hit": True,
                    "canary_id": str(rec.canary_id),
                    "kind": rec.kind,
                    "tag": rec.tag,
                    "session_id": str(rec.session_id) if rec.session_id else None,
                    "observed_session_id": str(obs_sid) if obs_sid else None,
                    "cross_session_reuse": False,
                    "matched_in": rec.trigger_meta.get("matched_in"),
                }
        return None

    def _log_cross_session_reuse(
        self,
        canary: CanaryRecord,
        observation: dict,
        principal: AuthenticatedPrincipal,
    ) -> None:
        """Log cross-session canary reuse attempt as a security event."""
        try:
            obs_sid = observation.get("session_id")
            obs_merchant = observation.get("merchant_id")
            obs_identity = observation.get("identity_id")
            evidence_payload = {
                "type": "canary_cross_session_reuse",
                "canary_id": str(canary.canary_id),
                "canary_kind": canary.kind,
                "canary_tag": canary.tag,
                "canary_session_id": str(canary.session_id) if canary.session_id else None,
                "canary_merchant_id": str(canary.merchant_id) if canary.merchant_id else None,
                "canary_identity_id": str(canary.identity_id) if canary.identity_id else None,
                "observed_session_id": str(obs_sid) if obs_sid else None,
                "observed_merchant_id": str(obs_merchant) if obs_merchant else None,
                "observed_identity_id": str(obs_identity) if obs_identity else None,
                "requesting_merchant_id": str(principal.merchant_id),
                "requesting_user_id": str(principal.user_id),
                "matched_in": observation.get("matched_in")
                if isinstance(observation, dict)
                else "unknown",
            }
            EvidenceChain(self.db).append("canary_cross_session_reuse", evidence_payload)
        except Exception:
            # Best effort logging; don't let logging failures affect canary logic
            pass
