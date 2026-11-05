"""
Security Vaccination tests.

Covers:
* Signature extraction from a confirmed attack (sanitized, no PII/secrets).
* Deterministic signature matching (sequence + action + corroborating features).
* Signature lifecycle API: create, approve, reject, revoke.
* Analyst-only authorization; merchant cannot approve/revoke/revoke.
* Tenant isolation: a merchant cannot manage another merchant's signatures.
* PROPOSED signatures are not applied; REVOKED signatures no longer match.
* Duplicate approval rejected; malformed lifecycle transitions rejected.
* Evidence hash-chain integrity across the lifecycle.
* Cross-merchant demonstration: Merchant A attack -> signature -> approval ->
  Merchant B same pattern matches with earlier detection via Trust Gateway.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import SecurityEvent
from app.models.session import SessionRecord
from app.models.vaccination import VaccinationMatch, VaccinationSignature
from app.schemas.sessions import SessionStatus, TrustLevel
from app.services.vaccination_service import SignatureMatcher
from tests.conftest import (
    OTHER_MERCHANT_ID,
    TEST_ANALYST_ID,
    TEST_MERCHANT_ID,
    TEST_USER_ID,
)

OTHER_USER_ID = uuid4()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _merchant_headers() -> dict:
    return {
        "Authorization": "Bearer dev-merchant-token",
        "X-Dev-Role": "merchant",
        "X-Dev-Merchant-Id": str(TEST_MERCHANT_ID),
        "X-Dev-User-Id": str(TEST_USER_ID),
    }


def _analyst_headers() -> dict:
    return {
        "Authorization": "Bearer dev-analyst-token",
        "X-Dev-Role": "analyst",
        "X-Dev-Merchant-Id": str(TEST_MERCHANT_ID),
        "X-Dev-User-Id": str(TEST_ANALYST_ID),
    }


def _other_merchant_headers() -> dict:
    return {
        "Authorization": "Bearer dev-other-merchant-token",
        "X-Dev-Role": "merchant",
        "X-Dev-Merchant-Id": str(OTHER_MERCHANT_ID),
        "X-Dev-User-Id": str(OTHER_USER_ID),
    }


def _other_analyst_headers() -> dict:
    return {
        "Authorization": "Bearer dev-analyst-token",
        "X-Dev-Role": "analyst",
        "X-Dev-Merchant-Id": str(OTHER_MERCHANT_ID),
        "X-Dev-User-Id": str(TEST_ANALYST_ID),
    }


def _create_attack_session(
    db: Session, merchant_id: UUID, user_id: UUID, session_id: UUID
) -> SessionRecord:
    """Create an active session that experienced a confirmed attack pattern."""
    now = datetime.now(timezone.utc)
    session = SessionRecord(
        session_id=session_id,
        user_id=user_id,
        merchant_id=merchant_id,
        trust_level=TrustLevel.ISOLATED.value,
        risk_score=95.0,
        status=SessionStatus.ACTIVE.value,
        device_fingerprint="attack-device-001",
        ip_address="203.0.113.42",
        last_activity_at=now,
    )
    db.add(session)
    db.flush()

    base = now - timedelta(hours=2)
    events = [
        SecurityEvent(
            event_id=uuid4(),
            session_id=session_id,
            merchant_id=merchant_id,
            user_id=user_id,
            event_type="payee_added",
            occurred_at=base,
            server_received_at=base,
            device_id="attack-device-001",
            ip_address="203.0.113.42",
            action="payee.add",
            metadata_payload={"recipient_email": "attacker-payee@example.test", "amount": 0.0},
            processed_by_risk_engine=True,
        ),
        SecurityEvent(
            event_id=uuid4(),
            session_id=session_id,
            merchant_id=merchant_id,
            user_id=user_id,
            event_type="payout",
            occurred_at=base + timedelta(minutes=5),
            server_received_at=base + timedelta(minutes=5),
            device_id="attack-device-001",
            ip_address="203.0.113.42",
            action="payout",
            metadata_payload={"recipient_email": "attacker-payee@example.test", "amount": 9000.0},
            processed_by_risk_engine=True,
        ),
    ]
    db.add_all(events)
    db.commit()
    db.refresh(session)
    return session


def _make_signature_payload(session_id: UUID) -> dict:
    return {
        "session_id": str(session_id),
        "name": "Payee-add-then-large-payout from new device",
        "description": "Confirmed account-takeover pattern: new device, new payee, large payout within 30 min.",
        "signature_definition": {
            "pattern": {
                "action_type": "payout",
                "event_sequence": [
                    {"event_type": "payee_added", "action_type": "payee.add"},
                    {"event_type": "payout", "action_type": "payout", "within_seconds": 1800},
                ],
                "requires_new_device": True,
                "requires_new_location": False,
                "requires_new_payee": True,
                "requires_large_payout": True,
                "amount_threshold": 5000.0,
                "within_seconds": 1800,
            }
        },
        "detection_confidence": 85.0,
        "evidence_refs": [],
    }


# --------------------------------------------------------------------------- #
# Signature extraction
# --------------------------------------------------------------------------- #
def test_signature_extraction_is_proposed_and_sanitized(client: TestClient, db_session: Session):
    session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    resp = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(session.session_id),
        headers=_merchant_headers(),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "PROPOSED"
    assert body["signature_id"]
    assert body["source_merchant_id"] == str(TEST_MERCHANT_ID)
    assert body["match_count"] == 0

    # Sanitized: no secrets, tokens, credentials, or raw customer PII.
    definition = body["signature_definition"]
    payload_text = str(definition)
    for forbidden in [
        "password",
        "secret",
        "access_token",
        "client_secret",
        "paypal",
        "sk_live",
        "example.test",
    ]:
        assert forbidden not in payload_text.lower(), f"forbidden field leaked: {forbidden}"
    assert "signature_hash" in definition
    assert definition["version"] == 1

    persisted = db_session.get(VaccinationSignature, UUID(body["signature_id"]))
    assert persisted is not None
    assert persisted.status == "PROPOSED"

    # Evidence recorded for creation.
    from app.models.evidence import EvidenceLogEntry

    assert (
        db_session.query(EvidenceLogEntry)
        .filter_by(event_ref="vaccination_signature_created")
        .first()
        is not None
    )


def test_signature_extraction_requires_own_session(client: TestClient, db_session: Session):
    session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    resp = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(session.session_id),
        headers=_other_merchant_headers(),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "SESSION_SCOPE_MISMATCH"


# --------------------------------------------------------------------------- #
# Deterministic matching (unit)
# --------------------------------------------------------------------------- #
def test_matcher_requires_action_and_sequence():
    matcher = SignatureMatcher()
    session_events = [
        {
            "event_type": "payee_added",
            "action": "payee.add",
            "device_id": "d1",
            "ip_address": "1.2.3.4",
            "recipient": "p1",
            "amount": 100.0,
            "occurred_at": datetime.now(timezone.utc),
        },
        {
            "event_type": "payout",
            "action": "payout",
            "device_id": "d1",
            "ip_address": "1.2.3.4",
            "recipient": "p1",
            "amount": 9000.0,
            "occurred_at": datetime.now(timezone.utc),
        },
    ]
    definition = {
        "version": 1,
        "pattern": {
            "action_type": "payout",
            "event_sequence": [
                {"event_type": "payee_added", "action_type": "payee.add"},
                {"event_type": "payout", "action_type": "payout", "within_seconds": 1800},
            ],
            "requires_new_device": True,
            "requires_new_payee": True,
            "requires_large_payout": True,
            "amount_threshold": 5000.0,
            "within_seconds": 1800,
        },
        "risk_indicators": {},
        "detection_confidence": 80.0,
        "evidence_refs": [],
        "signature_hash": "x",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Empty twin => everything is new for the merchant.
    class FakeTwin:
        confirmed_devices = []
        confirmed_locations = []

        def confirmed_payees(self, n):
            return set()

    class FakeRepo:
        def get_twin(self, m, u):
            return FakeTwin()

        def to_snapshot(self, t):
            return t

    req = type(
        "R",
        (),
        {"session_id": uuid4(), "amount": 9000.0, "action_type": "payout", "recipient": "p1"},
    )()
    result = matcher.match(
        signature_definition=definition,
        session_events=session_events,
        request=req,
        twin_repo=FakeRepo(),
        merchant_id=uuid4(),
    )
    assert result["matched"] is True
    assert result["score"] >= 60.0
    assert result["risk_points"] > 0
    assert "new_device" in result["matched_features"]
    assert "new_payee" in result["matched_features"]
    assert "large_payout" in result["matched_features"]
    assert "event_sequence" in result["matched_features"]


def test_matcher_rejects_wrong_action_type():
    definition = {
        "pattern": {"action_type": "payout", "event_sequence": []},
        "risk_indicators": {},
        "detection_confidence": 80.0,
        "evidence_refs": [],
        "signature_hash": "x",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    req = type(
        "R",
        (),
        {"session_id": uuid4(), "amount": 100.0, "action_type": "refund", "recipient": "p1"},
    )()
    result = SignatureMatcher.match(
        signature_definition=definition,
        session_events=[],
        request=req,
        twin_repo=None,
        merchant_id=uuid4(),
    )
    assert result["matched"] is False
    assert result["reason"] == "action_type_mismatch"


def test_matcher_rejects_missing_sequence():
    definition = {
        "pattern": {
            "action_type": "payout",
            "event_sequence": [
                {"event_type": "payee_added", "action_type": "payee.add"},
                {"event_type": "payout", "action_type": "payout", "within_seconds": 1800},
            ],
            "requires_new_device": True,
            "requires_new_payee": True,
            "amount_threshold": 5000.0,
            "within_seconds": 1800,
        },
        "risk_indicators": {},
        "detection_confidence": 80.0,
        "evidence_refs": [],
        "signature_hash": "x",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Session has only a payout, no preceding payee_add.
    session_events = [
        {
            "event_type": "payout",
            "action": "payout",
            "device_id": "d1",
            "ip_address": "1.2.3.4",
            "recipient": "p1",
            "amount": 9000.0,
            "occurred_at": datetime.now(timezone.utc),
        },
    ]
    req = type(
        "R",
        (),
        {"session_id": uuid4(), "amount": 9000.0, "action_type": "payout", "recipient": "p1"},
    )()

    class FakeRepo:
        def get_twin(self, m, u):
            return None

        def to_snapshot(self, t):
            return t

    result = SignatureMatcher.match(
        signature_definition=definition,
        session_events=session_events,
        request=req,
        twin_repo=FakeRepo(),
        merchant_id=uuid4(),
    )
    assert result["matched"] is False
    assert result["reason"] == "event_sequence_not_present"


# --------------------------------------------------------------------------- #
# Lifecycle API
# --------------------------------------------------------------------------- #
def test_lifecycle_propose_approve_activate(client: TestClient, db_session: Session):
    session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(session.session_id),
        headers=_merchant_headers(),
    )
    assert create.status_code == 201
    signature_id = create.json()["signature_id"]

    # Merchant cannot approve (analyst only).
    resp = client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve", json={}, headers=_merchant_headers()
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "ANALYST_ROLE_REQUIRED"

    # Analyst approves -> ACTIVE.
    resp = client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve",
        json={"notes": "Confirmed attack pattern"},
        headers=_analyst_headers(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new_status"] == "ACTIVE"
    assert body["analyst_id"] == str(TEST_ANALYST_ID)

    persisted = db_session.get(VaccinationSignature, UUID(signature_id))
    assert persisted.status == "ACTIVE"
    assert persisted.approved_by == TEST_ANALYST_ID
    assert persisted.approved_at is not None

    # Evidence for approval.
    from app.models.evidence import EvidenceLogEntry

    assert (
        db_session.query(EvidenceLogEntry)
        .filter_by(event_ref="vaccination_signature_approve")
        .first()
        is not None
    )


def test_duplicate_approval_rejected(client: TestClient, db_session: Session):
    session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(session.session_id),
        headers=_merchant_headers(),
    )
    signature_id = create.json()["signature_id"]
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve", json={}, headers=_analyst_headers()
    )

    resp = client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve", json={}, headers=_analyst_headers()
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "VACCINATION_NOT_PROPOSED"


def test_revoke_active_signature(client: TestClient, db_session: Session):
    session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(session.session_id),
        headers=_merchant_headers(),
    )
    signature_id = create.json()["signature_id"]
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve", json={}, headers=_analyst_headers()
    )

    resp = client.post(
        f"/v1/vaccination/signatures/{signature_id}/revoke",
        json={"notes": "False positive"},
        headers=_analyst_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["new_status"] == "REVOKED"

    persisted = db_session.get(VaccinationSignature, UUID(signature_id))
    assert persisted.status == "REVOKED"
    assert persisted.revoked_by == TEST_ANALYST_ID


def test_revoke_proposed_signature_rejected(client: TestClient, db_session: Session):
    session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(session.session_id),
        headers=_merchant_headers(),
    )
    signature_id = create.json()["signature_id"]

    resp = client.post(
        f"/v1/vaccination/signatures/{signature_id}/revoke", json={}, headers=_analyst_headers()
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "VACCINATION_NOT_ACTIVE"


def test_tenant_isolation_cannot_manage_foreign_signature(client: TestClient, db_session: Session):
    session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(session.session_id),
        headers=_merchant_headers(),
    )
    signature_id = create.json()["signature_id"]
    approve_path = f"/v1/vaccination/signatures/{signature_id}/approve"
    revoke_path = f"/v1/vaccination/signatures/{signature_id}/revoke"
    detail_path = f"/v1/vaccination/signatures/{signature_id}"

    # A non-analyst merchant cannot approve/revoke (authorization precedes scope).
    for path in [approve_path, revoke_path]:
        resp = client.post(path, json={}, headers=_other_merchant_headers())
        assert resp.status_code == 403, f"{path}: {resp.text}"
        assert resp.json()["error"]["code"] == "ANALYST_ROLE_REQUIRED"

    # Detail is scope-checked: another merchant cannot read Merchant A's signature.
    resp = client.get(detail_path, headers=_other_merchant_headers())
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "VACCINATION_SCOPE_MISMATCH"

    # Another merchant's analyst cannot manage Merchant A's signature (tenant isolation).
    for path in [approve_path, revoke_path]:
        resp = client.post(path, json={}, headers=_other_analyst_headers())
        assert resp.status_code == 403, f"{path}: {resp.text}"
        assert resp.json()["error"]["code"] == "VACCINATION_SCOPE_MISMATCH"


# --------------------------------------------------------------------------- #
# Proposed / revoked signatures are not applied
# --------------------------------------------------------------------------- #
def test_proposed_signature_not_applied(client: TestClient, db_session: Session):
    session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(session.session_id),
        headers=_merchant_headers(),
    )
    signature_id = create.json()["signature_id"]
    # Still PROPOSED: evaluate against Merchant B should not match.
    b_session = _create_attack_session(db_session, OTHER_MERCHANT_ID, OTHER_USER_ID, uuid4())
    resp = client.post(
        "/v1/vaccination/evaluate",
        json={
            "session_id": str(b_session.session_id),
            "amount": 9000.0,
            "recipient": "attacker-payee@example.test",
            "action_type": "payout",
            "event_type": "payout.execute",
        },
        headers=_other_merchant_headers(),
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["match"]
    assert detail["matched"] is False
    assert detail["signature_id"] is None

    # Now approve and re-evaluate: should match.
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve", json={}, headers=_analyst_headers()
    )
    resp = client.post(
        "/v1/vaccination/evaluate",
        json={
            "session_id": str(b_session.session_id),
            "amount": 9000.0,
            "recipient": "attacker-payee@example.test",
            "action_type": "payout",
            "event_type": "payout.execute",
        },
        headers=_other_merchant_headers(),
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["match"]
    assert detail["matched"] is True
    assert detail["signature_id"] == signature_id
    assert detail["risk_points"] > 0
    assert detail["match_score"] >= 60.0

    # Match recorded + evidence.
    persisted = (
        db_session.query(VaccinationMatch).filter_by(target_merchant_id=OTHER_MERCHANT_ID).first()
    )
    assert persisted is not None
    assert persisted.signature_id == UUID(signature_id)
    from app.models.evidence import EvidenceLogEntry

    assert (
        db_session.query(EvidenceLogEntry)
        .filter_by(event_ref="vaccination_signature_matched")
        .first()
        is not None
    )


def test_revoked_signature_no_longer_matches(client: TestClient, db_session: Session):
    session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(session.session_id),
        headers=_merchant_headers(),
    )
    signature_id = create.json()["signature_id"]
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve", json={}, headers=_analyst_headers()
    )
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/revoke", json={}, headers=_analyst_headers()
    )

    b_session = _create_attack_session(db_session, OTHER_MERCHANT_ID, OTHER_USER_ID, uuid4())
    resp = client.post(
        "/v1/vaccination/evaluate",
        json={
            "session_id": str(b_session.session_id),
            "amount": 9000.0,
            "recipient": "attacker-payee@example.test",
            "action_type": "payout",
            "event_type": "payout.execute",
        },
        headers=_other_merchant_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["match"]["matched"] is False


# --------------------------------------------------------------------------- #
# Evidence integrity across lifecycle
# --------------------------------------------------------------------------- #
def test_evidence_chain_valid_after_full_lifecycle(client: TestClient, db_session: Session):
    session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(session.session_id),
        headers=_merchant_headers(),
    )
    signature_id = create.json()["signature_id"]
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve",
        json={"notes": "ok"},
        headers=_analyst_headers(),
    )
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/revoke",
        json={"notes": "retired"},
        headers=_analyst_headers(),
    )

    resp = client.get("/v1/evidence/verify", headers=_merchant_headers())
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["valid"] is True, result


# --------------------------------------------------------------------------- #
# Cross-merchant demonstration via Trust Gateway
# --------------------------------------------------------------------------- #
def test_cross_merchant_second_merchant_protection(client: TestClient, db_session: Session):
    """Acceptance test: Merchant A attack -> signature -> approval ->
    Merchant B same pattern matches with earlier detection via Trust Gateway."""
    # Merchant A: confirmed attack.
    a_session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(a_session.session_id),
        headers=_merchant_headers(),
    )
    assert create.status_code == 201
    signature_id = create.json()["signature_id"]

    # Before approval: signature PROPOSED, Merchant B not protected.
    b_session = _create_attack_session(db_session, OTHER_MERCHANT_ID, OTHER_USER_ID, uuid4())
    before = client.post(
        "/v1/payouts",
        json={
            "session_id": str(b_session.session_id),
            "recipient_email": "attacker-payee@example.test",
            "amount": 9000.0,
            "currency": "USD",
            "reference_note": "attack replay",
            "idempotency_key": "cross-merchant-before-" + str(uuid4()),
        },
        headers=_other_merchant_headers(),
    )
    # before may be NORMAL/restricted based on twin; capture score.
    before_body = before.json()
    before_score = before_body.get("risk_score", 0.0)

    # Approve signature.
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve", json={}, headers=_analyst_headers()
    )

    # After approval: Merchant B same pattern via Trust Gateway -> vaccination match raises risk.
    b_session2 = _create_attack_session(db_session, OTHER_MERCHANT_ID, OTHER_USER_ID, uuid4())
    after = client.post(
        "/v1/payouts",
        json={
            "session_id": str(b_session2.session_id),
            "recipient_email": "attacker-payee@example.test",
            "amount": 9000.0,
            "currency": "USD",
            "reference_note": "attack replay",
            "idempotency_key": "cross-merchant-after-" + str(uuid4()),
        },
        headers=_other_merchant_headers(),
    )
    assert after.status_code == 200, after.text
    after_body = after.json()
    after_score = after_body.get("risk_score", 0.0)
    after_reasons = after_body.get("reason_codes", [])

    # Vaccination match should be recorded.
    match = db_session.query(VaccinationMatch).filter_by(target_merchant_id=OTHER_MERCHANT_ID).all()
    assert any(str(m.signature_id) == signature_id for m in match), (
        "no vaccination match recorded for Merchant B"
    )

    # Evidence verifies.
    resp = client.get("/v1/evidence/verify", headers=_merchant_headers())
    assert resp.status_code == 200
    assert resp.json()["valid"] is True

    # Earlier detection: after score >= before score and vaccination signal present.
    assert after_score >= before_score, f"after {after_score} < before {before_score}"
    assert any("VACCINATION" in r for r in after_reasons), (
        f"no vaccination reason in {after_reasons}"
    )
    # Merchant B's baseline is separate: Merchant A data never leaked (signature_definition has no PII).
    detail = client.get(
        f"/v1/vaccination/signatures/{signature_id}", headers=_merchant_headers()
    ).json()
    assert "attacker-payee@example.test" not in str(detail["signature_definition"])


# --------------------------------------------------------------------------- #
# Regression: Issue 1 — Match history serialization (signature_name)
# --------------------------------------------------------------------------- #
def test_match_history_empty_when_no_matches(client: TestClient, merchant_auth_headers: dict):
    """GET /v1/vaccination/matches returns HTTP 200 with empty array when no matches exist."""
    resp = client.get("/v1/vaccination/matches", headers=merchant_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_match_history_serializes_signature_name(client: TestClient, db_session: Session, merchant_auth_headers: dict):
    """After a match is recorded, match history returns signature_name without 500."""
    # Merchant A creates and approves a signature.
    a_session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(a_session.session_id),
        headers=_merchant_headers(),
    )
    assert create.status_code == 201
    signature_id = create.json()["signature_id"]
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve", json={}, headers=_analyst_headers()
    )

    # Merchant B evaluates a matching session -> match recorded.
    b_session = _create_attack_session(db_session, OTHER_MERCHANT_ID, OTHER_USER_ID, uuid4())
    resp = client.post(
        "/v1/vaccination/evaluate",
        json={
            "session_id": str(b_session.session_id),
            "amount": 9000.0,
            "recipient": "attacker-payee@example.test",
            "action_type": "payout",
            "event_type": "payout.execute",
        },
        headers=_other_merchant_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["match"]["matched"] is True

    # Merchant B's match history must serialize without 500 and include signature_name.
    resp = client.get("/v1/vaccination/matches", headers=_other_merchant_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    match = body["items"][0]
    assert match["signature_name"]  # non-empty: serialization fix works
    assert match["signature_id"] == signature_id
    assert match["target_merchant_id"] == str(OTHER_MERCHANT_ID)


# --------------------------------------------------------------------------- #
# Regression: Issue 1 — Tenant isolation on match history
# --------------------------------------------------------------------------- #
def test_match_history_tenant_isolation(client: TestClient, db_session: Session):
    """Merchant A must not see Merchant B's vaccination matches."""
    # Merchant A creates and approves a signature.
    a_session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(a_session.session_id),
        headers=_merchant_headers(),
    )
    assert create.status_code == 201
    signature_id = create.json()["signature_id"]
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve", json={}, headers=_analyst_headers()
    )

    # Merchant B evaluates a matching session -> match recorded for Merchant B.
    b_session = _create_attack_session(db_session, OTHER_MERCHANT_ID, OTHER_USER_ID, uuid4())
    resp = client.post(
        "/v1/vaccination/evaluate",
        json={
            "session_id": str(b_session.session_id),
            "amount": 9000.0,
            "recipient": "attacker-payee@example.test",
            "action_type": "payout",
            "event_type": "payout.execute",
        },
        headers=_other_merchant_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["match"]["matched"] is True

    # Merchant A's match history must be empty (different target_merchant_id).
    resp = client.get("/v1/vaccination/matches", headers=_merchant_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


# --------------------------------------------------------------------------- #
# Regression: Issue 2 — Session evaluation: not found / scope mismatch
# --------------------------------------------------------------------------- #
def test_evaluate_session_not_found(client: TestClient, merchant_auth_headers: dict):
    """POST /v1/vaccination/evaluate with a non-existent session returns 404."""
    resp = client.post(
        "/v1/vaccination/evaluate",
        json={
            "session_id": str(uuid4()),
            "amount": 100.0,
            "recipient": "x@y.test",
            "action_type": "payout",
            "event_type": "payout.execute",
        },
        headers=merchant_auth_headers,
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_evaluate_session_scope_mismatch(client: TestClient, db_session: Session):
    """POST /v1/vaccination/evaluate with a session from another merchant returns 403."""
    b_session = _create_attack_session(db_session, OTHER_MERCHANT_ID, OTHER_USER_ID, uuid4())
    resp = client.post(
        "/v1/vaccination/evaluate",
        json={
            "session_id": str(b_session.session_id),
            "amount": 100.0,
            "recipient": "x@y.test",
            "action_type": "payout",
            "event_type": "payout.execute",
        },
        headers=_merchant_headers(),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "SESSION_SCOPE_MISMATCH"


def test_evaluate_with_real_existing_session_produces_match(
    client: TestClient, db_session: Session
):
    """Full flow: real session -> evaluate against active signature -> match persisted."""
    # Merchant A: confirmed attack -> signature -> approved.
    a_session = _create_attack_session(db_session, TEST_MERCHANT_ID, TEST_USER_ID, uuid4())
    create = client.post(
        "/v1/vaccination/signatures",
        json=_make_signature_payload(a_session.session_id),
        headers=_merchant_headers(),
    )
    assert create.status_code == 201
    signature_id = create.json()["signature_id"]
    client.post(
        f"/v1/vaccination/signatures/{signature_id}/approve", json={}, headers=_analyst_headers()
    )

    # Merchant B: real existing session evaluated against active signature.
    b_session = _create_attack_session(db_session, OTHER_MERCHANT_ID, OTHER_USER_ID, uuid4())
    resp = client.post(
        "/v1/vaccination/evaluate",
        json={
            "session_id": str(b_session.session_id),
            "amount": 9000.0,
            "recipient": "attacker-payee@example.test",
            "action_type": "payout",
            "event_type": "payout.execute",
        },
        headers=_other_merchant_headers(),
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["match"]
    assert detail["matched"] is True
    assert detail["signature_id"] == signature_id
    assert detail["risk_points"] > 0
    assert detail["match_score"] >= 60.0

    # Match persisted and visible in Merchant B's match history.
    persisted = (
        db_session.query(VaccinationMatch)
        .filter_by(target_merchant_id=OTHER_MERCHANT_ID)
        .all()
    )
    assert any(str(m.signature_id) == signature_id for m in persisted)
