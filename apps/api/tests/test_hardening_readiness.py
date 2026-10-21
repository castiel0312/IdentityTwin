import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AuthenticationRequiredException,
    PaymentProviderException,
    ProviderRateLimitException,
    ProviderTimeoutException,
)
from app.gateway.provider import PayPalSandboxAdapter, mock_provider_instance
from app.models.incident import IncidentRecord
from app.models.session import SessionRecord
from app.schemas.payouts import PayoutRequest
from app.schemas.sessions import SessionStatus
from tests.conftest import (
    NORMAL_SESSION_ID,
    RESTRICTED_SESSION_ID,
    TEST_MERCHANT_ID,
    TEST_USER_ID,
)


def test_restricted_payout_exceeding_limit_rejected(
    client: TestClient, merchant_auth_headers: dict
):
    """
    Scenario 2:
    Restricted session attempting a payout exceeding the configured limit (500.00).
    Must be rejected with RESTRICTED_PAYOUT_LIMIT_EXCEEDED; provider never invoked.
    """
    mock_provider_instance.reset()
    payload = {
        "session_id": str(RESTRICTED_SESSION_ID),
        "recipient_email": "contractor@supplier.com",
        "amount": 750.00,  # Exceeds 500.00 limit
        "currency": "USD",
        "idempotency_key": "exceed-limit-" + str(uuid.uuid4()),
    }
    res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "rejected"
    assert data["trust_level"] == "RESTRICTED"
    assert data["action"] == "REQUIRE_STEP_UP"
    assert "RESTRICTED_PAYOUT_LIMIT_EXCEEDED" in data["reason_codes"]
    assert mock_provider_instance.invocation_count == 0


def test_restricted_payout_within_limit_without_step_up_rejected(
    client: TestClient, merchant_auth_headers: dict
):
    """
    Scenario 3a:
    Restricted session within limit (250.00 <= 500.00) but without step-up challenge verification token.
    Must require step-up challenge; provider never invoked.
    """
    mock_provider_instance.reset()
    payload = {
        "session_id": str(RESTRICTED_SESSION_ID),
        "recipient_email": "contractor@supplier.com",
        "amount": 250.00,
        "currency": "USD",
        "idempotency_key": "within-no-stepup-" + str(uuid.uuid4()),
    }
    res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "rejected"
    assert data["trust_level"] == "RESTRICTED"
    assert data["action"] == "REQUIRE_STEP_UP"
    assert "POLICY_ENFORCED_STEP_UP_CHALLENGE_REQUIRED" in data["reason_codes"]
    assert mock_provider_instance.invocation_count == 0


def test_restricted_payout_within_limit_with_step_up_allowed(
    client: TestClient, merchant_auth_headers: dict
):
    """
    Scenario 3b:
    Restricted session within limit (250.00) WITH valid step-up token.
    Payout is permitted under restricted clearance and invokes payment provider.
    """
    mock_provider_instance.reset()
    payload = {
        "session_id": str(RESTRICTED_SESSION_ID),
        "recipient_email": "contractor@supplier.com",
        "amount": 250.00,
        "currency": "USD",
        "idempotency_key": "within-stepup-ok-" + str(uuid.uuid4()),
        "step_up_token": "valid-step-up-token",
    }
    res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert data["trust_level"] == "RESTRICTED"
    assert data["action"] == "ALLOW"
    assert "RESTRICTED_STEP_UP_VERIFIED_PAYOUT_PERMITTED" in data["reason_codes"]
    assert mock_provider_instance.invocation_count == 1


def test_canary_event_forces_immediate_level_3_isolation(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    Scenario 6 & 13:
    Canary interaction forces immediate Level 3 isolation regardless of baseline score,
    terminates/revokes the session, and files an auditable IncidentRecord.
    """
    canary_session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    sess = SessionRecord(
        session_id=canary_session_id,
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        trust_level="NORMAL",
        risk_score=0.0,
        status=SessionStatus.ACTIVE.value,
        last_activity_at=now,
    )
    db_session.add(sess)
    db_session.commit()

    # Ingest event with canary trigger
    payload = {
        "event_type": "security.anomaly_detected",
        "session_id": str(canary_session_id),
        "occurred_at": now.isoformat(),
        "action": "canary.trap",
        "metadata": {"is_canary": True, "trap_signature": "honeypot_link_clicked"},
        "idempotency_key": "canary-evt-" + str(uuid.uuid4()),
    }
    res = client.post("/v1/events", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 201
    data = res.json()

    # Invariants: Trust level is ISOLATED, CANARY signal detected
    assert data["trust_level"] == "ISOLATED"
    assert "CANARY_INTERACTION" in data["risk_signals"]
    assert data["risk_signals"]["CANARY_INTERACTION"] == 11.0
    assert "CANARY_INTERACTION_LEVEL_3_OVERRIDE" in data["reason_codes"]

    # Verify session in DB was revoked / isolated
    db_session.refresh(sess)
    assert sess.trust_level == "ISOLATED"
    assert sess.status == SessionStatus.REVOKED.value

    # Verify an auditable incident was created with evidence integrity (Scenario 13)
    inc = db_session.query(IncidentRecord).filter_by(session_id=canary_session_id).first()
    assert inc is not None
    assert inc.severity == "CRITICAL"
    assert inc.status == "OPEN"
    assert "CANARY_INTERACTION" in str(inc.evidence_summary)


def test_paypal_webhook_invalid_signature_rejected(client: TestClient):
    """
    Scenario 15:
    Invalid PayPal webhook signature must return HTTP 400 Bad Request.
    """
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/certs/test",
        "paypal-transmission-id": "trans-bad-" + str(uuid.uuid4()),
        "paypal-transmission-sig": "TEST-INVALID-SIG",
        "paypal-transmission-time": "2026-10-21T14:30:00Z",
    }
    payload = {
        "id": "WH-TEST-BAD",
        "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
        "resource": {"payout_batch_id": "BATCH-123"},
    }
    res = client.post("/v1/webhooks/paypal", json=payload, headers=headers)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"


def test_paypal_webhook_valid_signature_and_deduplication(client: TestClient):
    """
    Scenario 15 & 10:
    Valid PayPal webhook processes successfully and deduplicates subsequent retries.
    """
    event_id = "WH-SUCCESS-" + str(uuid.uuid4())
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/certs/test",
        "paypal-transmission-id": event_id,
        "paypal-transmission-sig": "TEST-VALID-SIG",
        "paypal-transmission-time": "2026-10-21T14:30:00Z",
    }
    payload = {
        "id": event_id,
        "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
        "resource": {"batch_header": {"payout_batch_id": "BATCH-456"}},
    }

    # 1. First reception
    res1 = client.post("/v1/webhooks/paypal", json=payload, headers=headers)
    assert res1.status_code == 200
    assert res1.json()["status"] == "processed"

    # 2. Duplicate retry
    res2 = client.post("/v1/webhooks/paypal", json=payload, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate"


def test_paypal_sandbox_adapter_successful_execution():
    """
    Scenario 1 & 11:
    PayPalSandboxAdapter executes OAuth and Payouts API calls with proper headers.
    """
    adapter = PayPalSandboxAdapter(
        client_id="test_client_id",
        client_secret="test_client_secret",
        base_url="https://api-m.sandbox.paypal.com",
    )

    mock_oauth_response = MagicMock(spec=httpx.Response)
    mock_oauth_response.status_code = 200
    mock_oauth_response.json.return_value = {
        "access_token": "sandbox_access_token_abc123",
        "expires_in": 3600,
    }

    mock_payout_response = MagicMock(spec=httpx.Response)
    mock_payout_response.status_code = 201
    mock_payout_response.json.return_value = {
        "batch_header": {
            "payout_batch_id": "SANDBOX-BATCH-998877",
            "batch_status": "PENDING",
            "time_created": "2026-10-21T15:00:00Z",
        }
    }

    req = PayoutRequest(
        session_id=NORMAL_SESSION_ID,
        recipient_email="contractor@legit.com",
        amount=150.00,
        currency="USD",
        idempotency_key="paypal-test-key-001",
    )

    with patch("httpx.Client.post") as mock_post:
        mock_post.side_effect = [mock_oauth_response, mock_payout_response]
        result = adapter.execute_payout(req, TEST_MERCHANT_ID)

    assert result.success is True
    assert result.environment == "paypal_sandbox"
    assert result.provider_name == "paypal_sandbox"
    assert result.provider_transaction_id == "SANDBOX-BATCH-998877"
    assert result.details["batch_status"] == "PENDING"

    # Verify PayPal-Request-Id was passed
    payout_call_headers = mock_post.call_args_list[1].kwargs["headers"]
    assert payout_call_headers["PayPal-Request-Id"] == "paypal-test-key-001"
    assert "Bearer sandbox_access_token_abc123" in payout_call_headers["Authorization"]


def test_paypal_sandbox_adapter_auth_failure():
    """
    Scenario 11:
    PayPal Sandbox credentials rejected (401) raises AuthenticationRequiredException.
    """
    adapter = PayPalSandboxAdapter(
        client_id="invalid_client_id",
        client_secret="invalid_secret",
    )
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 401

    with patch("httpx.Client.post", return_value=mock_response):
        with pytest.raises(AuthenticationRequiredException):
            req = PayoutRequest(
                session_id=NORMAL_SESSION_ID,
                recipient_email="test@target.com",
                amount=50.00,
                idempotency_key="auth-fail-key-01",
            )
            adapter.execute_payout(req, TEST_MERCHANT_ID)


def test_paypal_sandbox_adapter_timeout():
    """
    Scenario 11:
    PayPal Sandbox timeout raises ProviderTimeoutException.
    """
    adapter = PayPalSandboxAdapter(
        client_id="test_client_id",
        client_secret="test_secret",
    )
    mock_oauth_response = MagicMock(spec=httpx.Response)
    mock_oauth_response.status_code = 200
    mock_oauth_response.json.return_value = {"access_token": "token_123", "expires_in": 3600}

    with patch("httpx.Client.post") as mock_post:
        # OAuth succeeds, but Payout call times out
        mock_post.side_effect = [
            mock_oauth_response,
            httpx.TimeoutException("Connection timed out"),
        ]
        with pytest.raises(ProviderTimeoutException):
            req = PayoutRequest(
                session_id=NORMAL_SESSION_ID,
                recipient_email="test@target.com",
                amount=50.00,
                idempotency_key="timeout-fail-key-01",
            )
            adapter.execute_payout(req, TEST_MERCHANT_ID)


def test_paypal_sandbox_adapter_rejection():
    """
    Scenario 11:
    PayPal Sandbox returns 422 Unprocessable raises PaymentProviderException.
    """
    adapter = PayPalSandboxAdapter(
        client_id="test_client_id",
        client_secret="test_secret",
    )
    mock_oauth_response = MagicMock(spec=httpx.Response)
    mock_oauth_response.status_code = 200
    mock_oauth_response.json.return_value = {"access_token": "token_123", "expires_in": 3600}

    mock_reject_response = MagicMock(spec=httpx.Response)
    mock_reject_response.status_code = 422
    mock_reject_response.json.return_value = {
        "name": "INSUFFICIENT_FUNDS",
        "message": "Account has insufficient funds for requested payout.",
    }

    with patch("httpx.Client.post") as mock_post:
        mock_post.side_effect = [mock_oauth_response, mock_reject_response]
        with pytest.raises(PaymentProviderException) as exc_info:
            req = PayoutRequest(
                session_id=NORMAL_SESSION_ID,
                recipient_email="test@target.com",
                amount=50.00,
                idempotency_key="reject-fail-key-01",
            )
            adapter.execute_payout(req, TEST_MERCHANT_ID)
        assert "INSUFFICIENT_FUNDS" in str(exc_info.value)


def test_paypal_sandbox_adapter_rate_limit():
    """
    Scenario 11:
    PayPal Sandbox returns 429 Too Many Requests raises ProviderRateLimitException.
    """
    adapter = PayPalSandboxAdapter(
        client_id="test_client_id",
        client_secret="test_secret",
    )
    mock_oauth_response = MagicMock(spec=httpx.Response)
    mock_oauth_response.status_code = 200
    mock_oauth_response.json.return_value = {"access_token": "token_123", "expires_in": 3600}

    mock_rate_limit_response = MagicMock(spec=httpx.Response)
    mock_rate_limit_response.status_code = 429

    with patch("httpx.Client.post") as mock_post:
        mock_post.side_effect = [mock_oauth_response, mock_rate_limit_response]
        with pytest.raises(ProviderRateLimitException):
            req = PayoutRequest(
                session_id=NORMAL_SESSION_ID,
                recipient_email="test@target.com",
                amount=50.00,
                idempotency_key="rate-limit-key-01",
            )
            adapter.execute_payout(req, TEST_MERCHANT_ID)
