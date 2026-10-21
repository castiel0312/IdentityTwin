import uuid

from fastapi.testclient import TestClient

from app.gateway.provider import mock_provider_instance
from tests.conftest import (
    DECOY_SESSION_ID,
    ISOLATED_SESSION_ID,
    NORMAL_SESSION_ID,
    RESTRICTED_SESSION_ID,
)


def test_client_cannot_override_trust_level_or_risk_score(
    client: TestClient, merchant_auth_headers: dict
):
    """
    Critical Invariant:
    Even if client sends `trust_level="NORMAL"` or `risk_score=0.0` in the payload for a RESTRICTED session,
    the server-side gateway policy evaluates the authoritative state and strictly denies / restricts it.
    Extra body attributes cannot manipulate routing!
    """
    mock_provider_instance.reset()
    payload = {
        "session_id": str(RESTRICTED_SESSION_ID),
        "recipient_email": "vendor@example.com",
        "amount": 250.00,
        "currency": "USD",
        "idempotency_key": "override-attempt-" + str(uuid.uuid4()),
        # Malicious client attempt to override server state
        # (Should either be forbidden by Pydantic extra='forbid' or ignored by gateway)
    }

    # Attempt with extra field to verify schema blocks tampering
    malicious_payload = dict(payload)
    malicious_payload["trust_level"] = "NORMAL"
    malicious_payload["risk_score"] = 0.0

    response = client.post("/v1/payouts", json=malicious_payload, headers=merchant_auth_headers)
    # Extra fields are forbidden by Pydantic config
    assert response.status_code == 422
    assert mock_provider_instance.invocation_count == 0


def test_normal_payout_invokes_provider_exactly_once(
    client: TestClient, merchant_auth_headers: dict
):
    """
    Requirement 5:
    Normal eligible payout invokes the mock provider adapter exactly once.
    """
    mock_provider_instance.reset()
    payload = {
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "contractor@legit.com",
        "amount": 1200.00,
        "currency": "USD",
        "reference_note": "Invoice #4021",
        "idempotency_key": "normal-payout-" + str(uuid.uuid4()),
    }

    response = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "completed"
    assert data["trust_level"] == "NORMAL"
    assert data["action"] == "ALLOW"
    assert data["routing_destination"] in ("PROVIDER_MOCK", "PROVIDER_PAYPAL")
    assert data["provider_reference"].startswith("SYNTH-MOCK-TXN-")
    assert mock_provider_instance.invocation_count == 1


def test_restricted_payout_does_not_invoke_provider(
    client: TestClient, merchant_auth_headers: dict
):
    """
    Requirement 6:
    Restricted payout rejects execution and does NOT invoke the payment provider.
    """
    mock_provider_instance.reset()
    payload = {
        "session_id": str(RESTRICTED_SESSION_ID),
        "recipient_email": "contractor@legit.com",
        "amount": 1200.00,
        "currency": "USD",
        "idempotency_key": "restricted-payout-" + str(uuid.uuid4()),
    }

    response = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "rejected"
    assert data["trust_level"] == "RESTRICTED"
    assert data["action"] == "REQUIRE_STEP_UP"
    assert data["routing_destination"] == "RESTRICTED_REJECT"
    assert data["provider_reference"] is None

    # CRITICAL INVARIANT: Provider was never touched
    assert mock_provider_instance.invocation_count == 0


def test_decoy_payout_does_not_invoke_provider(client: TestClient, merchant_auth_headers: dict):
    """
    Requirement 7:
    Decoy payout routes only to synthetic honey environment.
    Payment provider adapter is NEVER invoked.
    """
    mock_provider_instance.reset()
    payload = {
        "session_id": str(DECOY_SESSION_ID),
        "recipient_email": "hacker@honeypot.local",
        "amount": 5000.00,
        "currency": "USD",
        "idempotency_key": "decoy-payout-" + str(uuid.uuid4()),
    }

    response = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "decoy_completed"
    assert data["trust_level"] == "DECOY"
    assert data["action"] == "DECOY_FORWARD"
    assert data["routing_destination"] == "DECOY_HONEY"
    assert data["provider_reference"].startswith("HONEY-DECOY-SIM-TXN-")

    # CRITICAL INVARIANT: Real/Mock Payment Provider was never touched
    assert mock_provider_instance.invocation_count == 0


def test_isolated_payout_does_not_invoke_provider(client: TestClient, merchant_auth_headers: dict):
    """
    Requirement 8:
    Isolated payout is blocked and strictly denies sensitive operations.
    Payment provider adapter is NEVER invoked.
    """
    mock_provider_instance.reset()
    payload = {
        "session_id": str(ISOLATED_SESSION_ID),
        "recipient_email": "attacker@darkweb.org",
        "amount": 9999.00,
        "currency": "USD",
        "idempotency_key": "isolated-payout-" + str(uuid.uuid4()),
    }

    response = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "blocked"
    assert data["trust_level"] == "ISOLATED"
    assert data["action"] == "BLOCK"
    assert data["routing_destination"] == "ISOLATED_BLOCK"
    assert data["provider_reference"] is None

    # CRITICAL INVARIANT: Provider was never touched
    assert mock_provider_instance.invocation_count == 0
