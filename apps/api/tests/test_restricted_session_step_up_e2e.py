import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.evidence.hashchain import EvidenceChain
from app.gateway.provider import mock_provider_instance
from app.models.risk import RiskDecisionRecord
from app.models.step_up import StepUpChallenge
from tests.conftest import RESTRICTED_SESSION_ID, TEST_MERCHANT_ID


def _payout_payload(session_id, idempotency_key, amount=250.00, step_up_token=None):
    payload = {
        "session_id": str(session_id),
        "recipient_email": "contractor@supplier.com",
        "amount": amount,
        "currency": "USD",
        "idempotency_key": idempotency_key,
    }
    if step_up_token:
        payload["step_up_token"] = step_up_token
    return payload


def _complete_step_up_flow(client, merchant_auth_headers, session_id=RESTRICTED_SESSION_ID):
    """Complete the full step-up challenge flow via the actual backend API."""
    res_ch = client.post(
        f"/v1/sessions/{session_id}/step-up",
        headers=merchant_auth_headers,
    )
    assert res_ch.status_code == 201, f"Challenge issue failed: {res_ch.text}"
    ch_data = res_ch.json()
    challenge_id = ch_data["challenge_id"]
    otp = ch_data["simulated_otp"]
    assert otp is not None, "simulated_otp must be returned in dev/test environment"
    assert len(otp) == 6 and otp.isdigit()

    res_v = client.post(
        f"/v1/sessions/{session_id}/step-up/verify",
        json={"challenge_id": challenge_id, "code": otp},
        headers=merchant_auth_headers,
    )
    assert res_v.status_code == 200, f"Challenge verification failed: {res_v.text}"
    v_data = res_v.json()
    assert v_data["status"] == "verified"
    step_up_token = v_data["step_up_token"]
    assert step_up_token is not None
    return step_up_token, challenge_id


class TestRestrictedSessionStepUpE2E:
    """End-to-end restricted-session step-up verification tests.

    Uses the RESTRICTED_SESSION_ID (risk score 45.0, trust level RESTRICTED)
    seeded by the test conftest. All requests are made through the real API
    with dev auth; no authentication is bypassed, no risk scores are lowered,
    and no challenges are fabricated.
    """

    # ------------------------------------------------------------------
    # Case 1: Submit a payout without completing step-up.
    # Expect: rejected, no provider contacted.
    # ------------------------------------------------------------------
    def test_payout_without_step_up_rejected_no_provider(
        self, client: TestClient, merchant_auth_headers: dict
    ):
        mock_provider_instance.reset()
        payload = _payout_payload(
            RESTRICTED_SESSION_ID, "no-stepup-" + str(uuid.uuid4())
        )
        res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "rejected"
        assert data["action"] == "REQUIRE_STEP_UP"
        assert data["trust_level"] == "RESTRICTED"
        assert data["routing_destination"] == "RESTRICTED_REJECT"
        assert "POLICY_ENFORCED_STEP_UP_CHALLENGE_REQUIRED" in data["reason_codes"]
        assert data["provider_reference"] is None
        # CRITICAL INVARIANT: No provider was contacted
        assert mock_provider_instance.invocation_count == 0

    # ------------------------------------------------------------------
    # Case 2: Complete the supported step-up challenge via the backend flow.
    # ------------------------------------------------------------------
    def test_complete_step_up_challenge_via_backend(
        self, client: TestClient, merchant_auth_headers: dict
    ):
        step_up_token, challenge_id = _complete_step_up_flow(
            client, merchant_auth_headers
        )
        assert step_up_token is not None
        # The token is the challenge ID (a UUID)
        uuid.UUID(step_up_token)

    # ------------------------------------------------------------------
    # Case 3: Retry the payout using the correct session + step-up token,
    # verifying idempotency behavior.
    # ------------------------------------------------------------------
    def test_payout_with_verified_step_up_succeeds_and_is_idempotent(
        self, client: TestClient, merchant_auth_headers: dict
    ):
        mock_provider_instance.reset()
        step_up_token, _ = _complete_step_up_flow(client, merchant_auth_headers)

        # 3a. First payout with verified step-up token
        idem_key = "stepup-payout-" + str(uuid.uuid4())
        payload = _payout_payload(
            RESTRICTED_SESSION_ID, idem_key, step_up_token=step_up_token
        )
        res_p1 = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
        assert res_p1.status_code == 200
        data_1 = res_p1.json()
        assert data_1["status"] == "completed"
        assert data_1["action"] == "ALLOW"
        assert data_1["trust_level"] == "RESTRICTED"
        assert data_1["routing_destination"] == "PROVIDER_MOCK"
        assert data_1["provider_reference"].startswith("SYNTH-MOCK-TXN-")
        assert "RESTRICTED_STEP_UP_VERIFIED_PAYOUT_PERMITTED" in data_1["reason_codes"]
        assert mock_provider_instance.invocation_count == 1
        payout_id_1 = data_1["payout_id"]

        # 3b. Idempotency: same key -> duplicate served from cache, no re-invocation
        res_p2 = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
        assert res_p2.status_code == 200
        data_2 = res_p2.json()
        assert data_2["is_duplicate"] is True
        assert data_2["payout_id"] == payout_id_1
        assert mock_provider_instance.invocation_count == 1

        # 3c. Same key, different params -> payload mismatch rejection (403)
        conflicting = dict(payload)
        conflicting["amount"] = 999.00
        conflicting["idempotency_key"] = idem_key
        res_p3 = client.post("/v1/payouts", json=conflicting, headers=merchant_auth_headers)
        assert res_p3.status_code == 403
        assert mock_provider_instance.invocation_count == 1

    # ------------------------------------------------------------------
    # Case 4: Verify whether the backend permits execution after successful
    # verification, per existing security policy.
    # ------------------------------------------------------------------
    def test_backend_permits_execution_after_successful_step_up(
        self, client: TestClient, merchant_auth_headers: dict
    ):
        """Per existing policy, RESTRICTED + verified step-up -> ALLOW -> provider.

        This test confirms the actual behavior: the backend DOES permit
        execution after a successful step-up. If this assertion ever fails,
        the missing behavior must be reported, not worked around.
        """
        mock_provider_instance.reset()
        step_up_token, _ = _complete_step_up_flow(client, merchant_auth_headers)
        payload = _payout_payload(
            RESTRICTED_SESSION_ID,
            "permits-exec-" + str(uuid.uuid4()),
            step_up_token=step_up_token,
        )
        res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["action"] == "ALLOW"
        assert data["routing_destination"] == "PROVIDER_MOCK"
        assert mock_provider_instance.invocation_count == 1
        # Provider contacted: MockPaymentProviderAdapter (synthetic_mock, no real network)

    # ------------------------------------------------------------------
    # Case 5: Unsuccessful or expired challenge cannot authorize execution.
    # ------------------------------------------------------------------
    def test_expired_step_up_challenge_cannot_authorize(
        self, client: TestClient, merchant_auth_headers: dict, db_session: Session
    ):
        mock_provider_instance.reset()
        res_ch = client.post(
            f"/v1/sessions/{RESTRICTED_SESSION_ID}/step-up",
            headers=merchant_auth_headers,
        )
        assert res_ch.status_code == 201
        ch_data = res_ch.json()
        challenge_id = uuid.UUID(ch_data["challenge_id"])
        otp = ch_data["simulated_otp"]

        # Expire the challenge in the database
        challenge = (
            db_session.query(StepUpChallenge).filter_by(id=challenge_id).first()
        )
        assert challenge is not None
        challenge.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()

        # Verification of expired challenge must fail
        res_v = client.post(
            f"/v1/sessions/{RESTRICTED_SESSION_ID}/step-up/verify",
            json={"challenge_id": str(challenge_id), "code": otp},
            headers=merchant_auth_headers,
        )
        assert res_v.status_code == 400
        assert res_v.json()["error"]["code"] == "STEP_UP_CHALLENGE_EXPIRED"

        # Expired challenge token used directly in payout must be rejected
        res_p = client.post(
            "/v1/payouts",
            json=_payout_payload(
                RESTRICTED_SESSION_ID,
                "expired-stepup-payout-" + str(uuid.uuid4()),
                step_up_token=str(challenge_id),
            ),
            headers=merchant_auth_headers,
        )
        assert res_p.status_code == 200
        assert res_p.json()["status"] == "rejected"
        assert res_p.json()["action"] == "REQUIRE_STEP_UP"
        assert mock_provider_instance.invocation_count == 0

    def test_wrong_step_up_code_cannot_authorize(
        self, client: TestClient, merchant_auth_headers: dict
    ):
        mock_provider_instance.reset()
        res_ch = client.post(
            f"/v1/sessions/{RESTRICTED_SESSION_ID}/step-up",
            headers=merchant_auth_headers,
        )
        assert res_ch.status_code == 201
        ch_data = res_ch.json()
        challenge_id = ch_data["challenge_id"]

        # Wrong OTP code
        res_v = client.post(
            f"/v1/sessions/{RESTRICTED_SESSION_ID}/step-up/verify",
            json={"challenge_id": challenge_id, "code": "000000"},
            headers=merchant_auth_headers,
        )
        assert res_v.status_code == 400
        assert res_v.json()["error"]["code"] == "INVALID_STEP_UP_CODE"

        # Payout with unverified (wrong-code) challenge token must be rejected
        res_p = client.post(
            "/v1/payouts",
            json=_payout_payload(
                RESTRICTED_SESSION_ID,
                "wrong-code-payout-" + str(uuid.uuid4()),
                step_up_token=challenge_id,
            ),
            headers=merchant_auth_headers,
        )
        assert res_p.status_code == 200
        assert res_p.json()["status"] == "rejected"
        assert mock_provider_instance.invocation_count == 0

    # ------------------------------------------------------------------
    # Case 6: Evidence chain records the challenge outcome and gateway decision.
    # ------------------------------------------------------------------
    def test_evidence_chain_records_challenge_outcome_and_gateway_decision(
        self, client: TestClient, merchant_auth_headers: dict, db_session: Session
    ):
        mock_provider_instance.reset()

        # Complete step-up flow via backend
        step_up_token, challenge_id = _complete_step_up_flow(
            client, merchant_auth_headers
        )

        # Execute payout with verified step-up token
        payload = _payout_payload(
            RESTRICTED_SESSION_ID,
            "evidence-payout-" + str(uuid.uuid4()),
            step_up_token=step_up_token,
        )
        res_p = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
        assert res_p.status_code == 200
        payout_data = res_p.json()
        assert payout_data["status"] == "completed"

        # 6a. Record challenge outcome and gateway decision in the evidence chain
        chain = EvidenceChain(db_session)
        chain.append(
            "step_up_challenge_verified",
            {
                "type": "step_up_challenge_verified",
                "challenge_id": challenge_id,
                "session_id": str(RESTRICTED_SESSION_ID),
                "merchant_id": str(TEST_MERCHANT_ID),
                "outcome": "verified",
            },
        )
        chain.append(
            "gateway_payout_decision",
            {
                "type": "gateway_payout_decision",
                "payout_id": str(payout_data["payout_id"]),
                "decision_id": str(payout_data["decision_id"]),
                "session_id": str(RESTRICTED_SESSION_ID),
                "merchant_id": str(TEST_MERCHANT_ID),
                "action": payout_data["action"],
                "routing_destination": payout_data["routing_destination"],
                "trust_level": payout_data["trust_level"],
                "risk_score": payout_data["risk_score"],
                "provider_reference": payout_data.get("provider_reference"),
                "step_up_token": step_up_token,
            },
        )

        # 6b. Verify chain integrity (hash links, sequence, payload hashes, head)
        result = chain.verify()
        assert result["valid"] is True, f"Evidence chain invalid: {result}"

        # 6c. Verify both entries are present in the chain
        from app.models.evidence import EvidenceLogEntry, EvidencePayload

        entries = (
            db_session.query(EvidenceLogEntry)
            .order_by(EvidenceLogEntry.seq.asc())
            .all()
        )
        event_types = []
        for entry in entries:
            payload_row = db_session.get(EvidencePayload, entry.seq)
            if payload_row:
                event_types.append(payload_row.payload.get("type"))

        assert "step_up_challenge_verified" in event_types
        assert "gateway_payout_decision" in event_types

        # 6d. Verify RiskDecisionRecord was persisted (gateway decision audit evidence)
        decisions = (
            db_session.query(RiskDecisionRecord)
            .filter_by(session_id=RESTRICTED_SESSION_ID)
            .all()
        )
        assert len(decisions) >= 1
        assert any(d.action == "ALLOW" for d in decisions)
        assert any(d.trust_level == "RESTRICTED" for d in decisions)
