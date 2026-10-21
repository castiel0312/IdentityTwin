import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateRequestException
from app.db.repositories.idempotency_repo import IdempotencyRepository
from app.gateway.provider import mock_provider_instance
from app.models.idempotency import IdempotencyRecord
from app.models.incident import IncidentRecord
from app.models.principal import User
from app.models.session import SessionRecord
from app.schemas.incidents import IncidentSeverity, IncidentStatus
from app.schemas.sessions import SessionStatus
from tests.conftest import (
    ISOLATED_SESSION_ID,
    NORMAL_SESSION_ID,
    OTHER_MERCHANT_ID,
    TEST_MERCHANT_ID,
    TEST_USER_ID,
)


def test_dev_auth_header_only_impersonation_blocked(client: TestClient):
    """
    Finding 4 Regression Test:
    Sending X-Dev-Role: analyst or X-Dev-Merchant-Id without any Bearer token
    must be strictly rejected with HTTP 401 Unauthorized.
    """
    res = client.get(
        "/v1/incidents",
        headers={
            "X-Dev-Role": "analyst",
            "X-Dev-Merchant-Id": str(TEST_MERCHANT_ID),
        },
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_unrecognized_bearer_token_rejected(client: TestClient):
    """
    Finding 4 Regression Test:
    Arbitrary or unrecognized bearer tokens must not fall through to valid merchant access.
    """
    res = client.get(
        "/v1/sessions",
        headers={"Authorization": "Bearer arbitrary-untrusted-token-xyz"},
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_idempotency_payload_tampering_rejected(client: TestClient, merchant_auth_headers: dict):
    """
    Finding 2 Regression Test:
    Reusing an idempotency key with different request parameters (amount/recipient)
    must be rejected to prevent parameter mutation or double-spend ambiguity.
    """
    mock_provider_instance.reset()
    idemp_key = "tamper-check-" + str(uuid.uuid4())

    # 1. First legitimate payout
    payload1 = {
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "alice@legit.com",
        "amount": 100.00,
        "currency": "USD",
        "idempotency_key": idemp_key,
    }
    res1 = client.post("/v1/payouts", json=payload1, headers=merchant_auth_headers)
    assert res1.status_code == 200
    assert mock_provider_instance.invocation_count == 1

    # 2. Tampered payout reusing the same idempotency key with different amount and recipient
    payload2 = {
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "attacker@evil.com",
        "amount": 50000.00,
        "currency": "USD",
        "idempotency_key": idemp_key,
    }
    res2 = client.post("/v1/payouts", json=payload2, headers=merchant_auth_headers)
    assert res2.status_code == 403
    assert res2.json()["error"]["code"] == "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"

    # Invariant: Provider was NOT called a second time
    assert mock_provider_instance.invocation_count == 1


def test_post_provider_failure_prevents_duplicate_provider_execution(
    client: TestClient, merchant_auth_headers: dict
):
    """
    Finding 1 Regression Test (CRITICAL):
    If a database error occurs AFTER the payment provider has already executed,
    subsequent retries with the same idempotency key MUST NOT invoke the provider again!
    """
    mock_provider_instance.reset()
    idemp_key = "crash-recovery-" + str(uuid.uuid4())
    payload = {
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "contractor@supplier.com",
        "amount": 250.00,
        "currency": "USD",
        "idempotency_key": idemp_key,
    }

    # Simulate database crash on payout_repo.create (after provider_adapter.execute_payout succeeded)
    client_no_raise = TestClient(client.app, raise_server_exceptions=False)
    with patch(
        "app.db.repositories.payout_repo.PayoutRepository.create",
        side_effect=RuntimeError("Simulated Database Disk Failure During Payout Persistence"),
    ):
        res1 = client_no_raise.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
        assert res1.status_code == 500

    # Provider WAS invoked during the first attempt
    assert mock_provider_instance.invocation_count == 1

    # Now the client retries the request with the identical idempotency key
    res2 = client_no_raise.post("/v1/payouts", json=payload, headers=merchant_auth_headers)

    # CRITICAL INVARIANT: The gateway MUST NOT invoke the provider again!
    assert res2.status_code == 403
    assert res2.json()["error"]["code"] == "PAYOUT_ALREADY_EXECUTED_RECONCILIATION_REQUIRED"
    assert mock_provider_instance.invocation_count == 1


def test_corrupted_trust_state_fails_closed_to_isolation(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    Finding 5 Regression Test:
    A session with an unknown or corrupted trust level must NEVER fall back to NORMAL.
    Must fail-closed to ISOLATED and block payout execution.
    """
    mock_provider_instance.reset()
    corrupt_session_id = uuid.uuid4()
    corrupt_session = SessionRecord(
        session_id=corrupt_session_id,
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        trust_level="CORRUPTED_TAMPERED_STATE",
        risk_score=0.0,
        status=SessionStatus.ACTIVE.value,
    )
    db_session.add(corrupt_session)
    db_session.commit()

    payload = {
        "session_id": str(corrupt_session_id),
        "recipient_email": "vendor@target.com",
        "amount": 300.00,
        "currency": "USD",
        "idempotency_key": "corrupt-check-" + str(uuid.uuid4()),
    }

    res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 200
    data = res.json()

    # Fail-closed invariant: must be blocked under ISOLATED
    assert data["status"] == "blocked"
    assert data["trust_level"] == "ISOLATED"
    assert data["action"] == "BLOCK"
    assert "CORRUPTED_TRUST_STATE_FAIL_CLOSED" in data["reason_codes"]
    assert mock_provider_instance.invocation_count == 0


def test_elevated_session_risk_score_is_preserved_and_restricted(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    Finding 5 Regression Test:
    If a session has an elevated risk score (e.g. 65.0), the risk engine must not
    reset the score to 0.0 baseline. The gateway policy must enforce RESTRICTED_REJECT.
    """
    mock_provider_instance.reset()
    elevated_session_id = uuid.uuid4()
    elevated_session = SessionRecord(
        session_id=elevated_session_id,
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        trust_level="NORMAL",
        risk_score=45.0,  # Elevated score in Restricted range (30-59)
        status=SessionStatus.ACTIVE.value,
    )
    db_session.add(elevated_session)
    db_session.commit()

    payload = {
        "session_id": str(elevated_session_id),
        "recipient_email": "vendor@target.com",
        "amount": 100.00,
        "currency": "USD",
        "idempotency_key": "elevated-check-" + str(uuid.uuid4()),
    }

    res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "rejected"
    assert data["trust_level"] == "RESTRICTED"
    assert data["risk_score"] >= 45.0
    assert data["action"] == "REQUIRE_STEP_UP"
    assert mock_provider_instance.invocation_count == 0


def test_inactive_session_fails_closed_without_invoking_provider(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    Guarantees: Missing, invalid, or inactive session trust state must fail closed.
    A suspended session cannot invoke the payment provider and returns HTTP 403 INACTIVE_SESSION.
    """
    mock_provider_instance.reset()
    revoked_session_id = uuid.uuid4()
    revoked_session = SessionRecord(
        session_id=revoked_session_id,
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        trust_level="NORMAL",
        risk_score=0.0,
        status=SessionStatus.REVOKED.value,
    )
    db_session.add(revoked_session)
    db_session.commit()

    payload = {
        "session_id": str(revoked_session_id),
        "recipient_email": "contractor@supplier.com",
        "amount": 200.00,
        "currency": "USD",
        "idempotency_key": "inactive-check-" + str(uuid.uuid4()),
    }

    res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "INACTIVE_SESSION"
    assert mock_provider_instance.invocation_count == 0


def test_idempotency_key_is_scoped_by_merchant(
    client: TestClient,
    merchant_auth_headers: dict,
    other_merchant_auth_headers: dict,
    db_session: Session,
):
    """
    Guarantees: Idempotency keys are strictly bound to merchant scope.
    Two different merchants using the exact same idempotency key string
    must execute independently without collision or leaking cached responses.
    """
    mock_provider_instance.reset()
    shared_key = "cross-merchant-shared-key-" + str(uuid.uuid4())

    # Create a valid active session for OTHER_MERCHANT_ID
    other_user_id = uuid.UUID(other_merchant_auth_headers["X-Dev-User-Id"])
    other_user = User(
        user_id=other_user_id,
        merchant_id=OTHER_MERCHANT_ID,
        email="user@other-merchant.com",
        role="merchant",
    )
    other_session_id = uuid.uuid4()
    other_session = SessionRecord(
        session_id=other_session_id,
        user_id=other_user_id,
        merchant_id=OTHER_MERCHANT_ID,
        trust_level="NORMAL",
        risk_score=0.0,
        status=SessionStatus.ACTIVE.value,
        last_activity_at=datetime.now(timezone.utc),
    )
    db_session.add_all([other_user, other_session])
    db_session.commit()

    # 1. Merchant 1 executes payout
    payload1 = {
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "m1-vendor@domain.com",
        "amount": 100.00,
        "currency": "USD",
        "idempotency_key": shared_key,
    }
    res1 = client.post("/v1/payouts", json=payload1, headers=merchant_auth_headers)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "completed"
    assert data1["is_duplicate"] is False
    assert mock_provider_instance.invocation_count == 1

    # 2. Other Merchant executes payout with the SAME idempotency key string
    payload2 = {
        "session_id": str(other_session_id),
        "recipient_email": "m2-vendor@domain.com",
        "amount": 200.00,
        "currency": "USD",
        "idempotency_key": shared_key,
    }
    res2 = client.post("/v1/payouts", json=payload2, headers=other_merchant_auth_headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "completed"
    assert data2["is_duplicate"] is False
    assert data2["payout_id"] != data1["payout_id"]
    assert data2["provider_reference"] != data1["provider_reference"]

    # Invariant: Both legitimate merchant requests were processed by provider independently
    assert mock_provider_instance.invocation_count == 2


def test_incident_approval_does_not_bypass_payout_policy(
    client: TestClient,
    analyst_auth_headers: dict,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """
    Guarantees: Incident approval cannot bypass payout policy.
    Even when an analyst approves an incident associated with an ISOLATED session,
    the Trust Gateway continues to enforce server-side trust policy and blocks payout execution.
    """
    mock_provider_instance.reset()

    # Create an incident specifically associated with ISOLATED_SESSION_ID
    isolated_incident_id = uuid.uuid4()
    incident = IncidentRecord(
        incident_id=isolated_incident_id,
        merchant_id=TEST_MERCHANT_ID,
        session_id=ISOLATED_SESSION_ID,
        title="Critical Account Takeover Anomaly",
        description="Session locked down under ISOLATED status.",
        severity=IncidentSeverity.CRITICAL.value,
        status=IncidentStatus.OPEN.value,
        risk_score=95.0,
        trigger_reason="BIOMETRIC_MISMATCH_SUSPECTED_BOT",
    )
    db_session.add(incident)
    db_session.commit()

    # 1. Analyst approves the incident review
    approve_res = client.post(
        f"/v1/incidents/{isolated_incident_id}/approve",
        json={"notes": "Reviewed investigation details. Approving case notes."},
        headers=analyst_auth_headers,
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["action"] == "approved"
    assert approve_res.json()["new_status"] == "APPROVED"

    # 2. Merchant attempts payout using the ISOLATED session whose incident was approved
    payout_payload = {
        "session_id": str(ISOLATED_SESSION_ID),
        "recipient_email": "attacker@payout.org",
        "amount": 500.00,
        "currency": "USD",
        "idempotency_key": "incident-bypass-attempt-" + str(uuid.uuid4()),
    }
    payout_res = client.post("/v1/payouts", json=payout_payload, headers=merchant_auth_headers)
    assert payout_res.status_code == 200
    data = payout_res.json()

    # CRITICAL INVARIANT: The payout remains BLOCKED. Approval did not weaken gateway policy!
    assert data["status"] == "blocked"
    assert data["trust_level"] == "ISOLATED"
    assert data["action"] == "BLOCK"
    assert data["provider_reference"] is None
    assert mock_provider_instance.invocation_count == 0


def test_concurrent_duplicate_idempotency_keys_handled_safely(
    db_session: Session,
):
    """
    Guarantees: Concurrent duplicate requests cannot execute the same payout twice.
    Verifies that simultaneous repository-level insertions of the same (merchant_id, idempotency_key)
    enforce the unique constraint and raise DuplicateRequestException.
    """
    repo = IdempotencyRepository(db_session)
    key = "concurrent-key-" + str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    rec1 = IdempotencyRecord(
        idempotency_key=key,
        merchant_id=TEST_MERCHANT_ID,
        request_hash="hash1",
        status="processing",
        expires_at=now + timedelta(hours=24),
    )
    repo.save_record(rec1)

    # Attempting to save duplicate idempotency record for same merchant raises DuplicateRequestException
    rec2 = IdempotencyRecord(
        idempotency_key=key,
        merchant_id=TEST_MERCHANT_ID,
        request_hash="hash1",
        status="processing",
        expires_at=now + timedelta(hours=24),
    )
    with pytest.raises(DuplicateRequestException):
        repo.save_record(rec2)
