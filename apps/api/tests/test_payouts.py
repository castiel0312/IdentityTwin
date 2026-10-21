import uuid

from fastapi.testclient import TestClient

from app.gateway.provider import mock_provider_instance
from tests.conftest import NORMAL_SESSION_ID


def test_duplicate_payout_requests_do_not_execute_twice(
    client: TestClient, merchant_auth_headers: dict
):
    """
    Requirement 9:
    Duplicate payout requests with identical idempotency key do not execute twice.
    Provider adapter is invoked only once; second request returns cached response.
    """
    mock_provider_instance.reset()
    idempotency_key = "idemp-" + str(uuid.uuid4())
    payload = {
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "contractor@safe.com",
        "amount": 750.00,
        "currency": "USD",
        "reference_note": "Bi-weekly contractor payout",
        "idempotency_key": idempotency_key,
    }

    # 1. First execution
    resp1 = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["status"] == "completed"
    assert data1["is_duplicate"] is False
    assert mock_provider_instance.invocation_count == 1
    first_tx_ref = data1["provider_reference"]

    # 2. Second execution with identical idempotency key
    resp2 = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "completed"
    assert data2["is_duplicate"] is True
    assert data2["provider_reference"] == first_tx_ref

    # CRITICAL INVARIANT: Provider was NOT called a second time
    assert mock_provider_instance.invocation_count == 1


def test_payout_negative_amount_rejected(client: TestClient, merchant_auth_headers: dict):
    payload = {
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "contractor@safe.com",
        "amount": -50.00,
        "currency": "USD",
        "idempotency_key": "neg-amt-" + str(uuid.uuid4()),
    }
    response = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 422


def test_payout_invalid_email_format_rejected(client: TestClient, merchant_auth_headers: dict):
    payload = {
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "not-an-email",
        "amount": 100.00,
        "currency": "USD",
        "idempotency_key": "bad-email-" + str(uuid.uuid4()),
    }
    response = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 422


def test_payout_session_ownership_mismatch_rejected(
    client: TestClient, other_merchant_auth_headers: dict
):
    """
    Caller from other merchant attempts to initiate payout using another merchant's session.
    Must return 403 Forbidden.
    """
    mock_provider_instance.reset()
    payload = {
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "vendor@target.com",
        "amount": 500.00,
        "currency": "USD",
        "idempotency_key": "mismatch-" + str(uuid.uuid4()),
    }
    response = client.post("/v1/payouts", json=payload, headers=other_merchant_auth_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SESSION_OWNERSHIP_MISMATCH"
    assert mock_provider_instance.invocation_count == 0
