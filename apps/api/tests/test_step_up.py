import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.gateway.provider import mock_provider_instance
from app.models.step_up import StepUpChallenge
from tests.conftest import NORMAL_SESSION_ID, RESTRICTED_SESSION_ID


def test_forged_step_up_token_rejected(client: TestClient, merchant_auth_headers: dict):
    mock_provider_instance.reset()
    payload = {
        "session_id": str(RESTRICTED_SESSION_ID),
        "recipient_email": "contractor@supplier.com",
        "amount": 250.00,
        "currency": "USD",
        "idempotency_key": "forged-stepup-" + str(uuid.uuid4()),
        "step_up_token": str(uuid.uuid4()),  # Valid UUID format, but forged / nonexistent
    }
    res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "rejected"
    assert data["action"] == "REQUIRE_STEP_UP"
    assert "POLICY_ENFORCED_STEP_UP_CHALLENGE_REQUIRED" in data["reason_codes"]
    assert mock_provider_instance.invocation_count == 0


def test_reused_step_up_token_rejected(client: TestClient, merchant_auth_headers: dict):
    mock_provider_instance.reset()

    # 1. Issue challenge
    res_ch = client.post(
        f"/v1/sessions/{RESTRICTED_SESSION_ID}/step-up",
        headers=merchant_auth_headers,
    )
    assert res_ch.status_code == 201
    ch_data = res_ch.json()
    challenge_id = ch_data["challenge_id"]
    otp = ch_data["simulated_otp"]

    # 2. Verify challenge
    res_v = client.post(
        f"/v1/sessions/{RESTRICTED_SESSION_ID}/step-up/verify",
        json={"challenge_id": challenge_id, "code": otp},
        headers=merchant_auth_headers,
    )
    assert res_v.status_code == 200
    token = res_v.json()["step_up_token"]

    # 3. First payout execution succeeds and consumes the single-use token
    payload_1 = {
        "session_id": str(RESTRICTED_SESSION_ID),
        "recipient_email": "contractor@supplier.com",
        "amount": 200.00,
        "currency": "USD",
        "idempotency_key": "stepup-first-" + str(uuid.uuid4()),
        "step_up_token": token,
    }
    res_p1 = client.post("/v1/payouts", json=payload_1, headers=merchant_auth_headers)
    assert res_p1.status_code == 200
    assert res_p1.json()["status"] == "completed"
    assert mock_provider_instance.invocation_count == 1

    # 4. Reusing the same token on a new payout MUST be rejected
    payload_2 = {
        "session_id": str(RESTRICTED_SESSION_ID),
        "recipient_email": "contractor@supplier.com",
        "amount": 200.00,
        "currency": "USD",
        "idempotency_key": "stepup-reuse-" + str(uuid.uuid4()),
        "step_up_token": token,
    }
    res_p2 = client.post("/v1/payouts", json=payload_2, headers=merchant_auth_headers)
    assert res_p2.status_code == 200
    data_2 = res_p2.json()
    assert data_2["status"] == "rejected"
    assert data_2["action"] == "REQUIRE_STEP_UP"
    assert "POLICY_ENFORCED_STEP_UP_CHALLENGE_REQUIRED" in data_2["reason_codes"]
    # Provider invocation count must NOT have increased!
    assert mock_provider_instance.invocation_count == 1


def test_expired_step_up_challenge_rejected(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    mock_provider_instance.reset()

    # 1. Issue challenge
    res_ch = client.post(
        f"/v1/sessions/{RESTRICTED_SESSION_ID}/step-up",
        headers=merchant_auth_headers,
    )
    assert res_ch.status_code == 201
    ch_data = res_ch.json()
    challenge_id = uuid.UUID(ch_data["challenge_id"])
    otp = ch_data["simulated_otp"]

    # 2. Simulate challenge expiration in database
    challenge = db_session.query(StepUpChallenge).filter_by(id=challenge_id).first()
    assert challenge is not None
    challenge.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    # 3. Verification attempt on expired challenge must fail with 400
    res_v = client.post(
        f"/v1/sessions/{RESTRICTED_SESSION_ID}/step-up/verify",
        json={"challenge_id": str(challenge_id), "code": otp},
        headers=merchant_auth_headers,
    )
    assert res_v.status_code == 400
    assert res_v.json()["error"]["code"] == "STEP_UP_CHALLENGE_EXPIRED"

    # 4. Attempting to use expired challenge token directly in payout must be rejected
    payload = {
        "session_id": str(RESTRICTED_SESSION_ID),
        "recipient_email": "contractor@supplier.com",
        "amount": 250.00,
        "currency": "USD",
        "idempotency_key": "expired-stepup-" + str(uuid.uuid4()),
        "step_up_token": str(challenge_id),
    }
    res_p = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res_p.status_code == 200
    assert res_p.json()["status"] == "rejected"
    assert mock_provider_instance.invocation_count == 0


def test_other_session_step_up_token_rejected(client: TestClient, merchant_auth_headers: dict):
    mock_provider_instance.reset()

    # 1. Issue and verify challenge for Session A (NORMAL_SESSION_ID)
    res_ch = client.post(
        f"/v1/sessions/{NORMAL_SESSION_ID}/step-up",
        headers=merchant_auth_headers,
    )
    assert res_ch.status_code == 201
    ch_data = res_ch.json()
    res_v = client.post(
        f"/v1/sessions/{NORMAL_SESSION_ID}/step-up/verify",
        json={"challenge_id": ch_data["challenge_id"], "code": ch_data["simulated_otp"]},
        headers=merchant_auth_headers,
    )
    assert res_v.status_code == 200
    session_a_token = res_v.json()["step_up_token"]

    # 2. Try to use Session A's token on Session B (RESTRICTED_SESSION_ID)
    payload = {
        "session_id": str(RESTRICTED_SESSION_ID),
        "recipient_email": "contractor@supplier.com",
        "amount": 250.00,
        "currency": "USD",
        "idempotency_key": "cross-session-stepup-" + str(uuid.uuid4()),
        "step_up_token": session_a_token,
    }
    res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "rejected"
    assert data["action"] == "REQUIRE_STEP_UP"
    assert "POLICY_ENFORCED_STEP_UP_CHALLENGE_REQUIRED" in data["reason_codes"]
    assert mock_provider_instance.invocation_count == 0
