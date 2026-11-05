"""
End-to-end integration tests for IdentityTwin.

These tests exercise the running FastAPI application through TestClient
against a disposable SQLite database (see tests/conftest.py). They verify the
complete attack-replay and security-invariant flows end to end:

1. Attack replay / canary drill (POST /v1/simulate/attack):
   session creation, honey bootstrap, canary trigger, containment, incident,
   evidence chain, no real payment-provider invocation.

2. Evidence hash-chain integrity (GET /v1/evidence/verify): a valid sequence
   verifies; a tampered disposable record fails verification.

3. Honey/DECOY isolation: decoy payouts route to honey and never invoke the
   configured payment provider adapter.

4. Idempotency: duplicate payouts are served from cache without a second
   provider invocation.

The PayPal Sandbox adapter is never pointed at the real network in these
tests; the mock provider is used and its invocation count is asserted.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.security import AuthenticatedPrincipal, RoleEnum
from app.db.session import SessionLocal
from app.evidence.hashchain import EvidenceChain
from app.gateway.provider import mock_provider_instance
from app.models.evidence import EvidenceLogEntry, EvidencePayload
from app.models.session import SessionRecord
from app.schemas.payouts import PayoutRequest
from app.schemas.sessions import SessionStatus, TrustLevel
from tests.conftest import (
    DECOY_SESSION_ID,
    NORMAL_SESSION_ID,
    TEST_MERCHANT_ID,
    TEST_USER_ID,
)


def _headers() -> dict:
    return {
        "Authorization": "Bearer dev-merchant-token",
        "X-Dev-Role": "merchant",
        "X-Dev-Merchant-Id": str(TEST_MERCHANT_ID),
        "X-Dev-User-Id": str(TEST_USER_ID),
    }


@pytest.fixture(autouse=True)
def _reset_provider():
    mock_provider_instance.reset()
    yield
    mock_provider_instance.reset()


# ----------------------------------------------------------------------
# Attack replay / canary drill (POST /v1/simulate/attack)
# ----------------------------------------------------------------------


def test_attack_replay_canary_drill_runs_end_to_end(client: TestClient, db_session: SessionLocal):
    """
    Full attack replay: synthetic session, honey bootstrap, canary trigger,
    containment/isolation, incident sealed, evidence chain verified, and no
    real payment-provider invocation.
    """
    mock_provider_instance.reset()

    resp = client.post("/v1/simulate/attack", headers=_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] == "ok"
    assert body["session_id"]
    assert body["incident_sealed"] is True
    assert body["incident_id"]

    verify = body["evidence_verify"]
    assert verify["valid"] is True, verify
    assert verify["checked"] >= 1

    # The drill must not invoke the real payment provider (mock counts as the
    # provider seam; it must stay at zero for a canary/containment drill).
    assert mock_provider_instance.invocation_count == 0


def test_attack_replay_isolates_session_and_opens_incident(
    client: TestClient, db_session: SessionLocal
):
    resp = client.post("/v1/simulate/attack", headers=_headers())
    assert resp.status_code == 200
    incident_id = resp.json()["incident_id"]

    from app.models.incident import IncidentRecord

    incident = db_session.get(IncidentRecord, uuid.UUID(incident_id))
    assert incident is not None
    assert incident.status in ("OPEN", "UNDER_REVIEW", "APPROVED", "RESOLVED")
    assert incident.merchant_id == TEST_MERCHANT_ID


# ----------------------------------------------------------------------
# Evidence hash-chain integrity (GET /v1/evidence/verify)
# ----------------------------------------------------------------------


def test_evidence_chain_verifies_after_drill(client: TestClient):
    client.post("/v1/simulate/attack", headers=_headers())

    resp = client.get("/v1/evidence/verify", headers=_headers())
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["valid"] is True, result
    assert result["checked"] >= 1


def test_evidence_tampering_is_detected(client: TestClient, db_session: SessionLocal):
    """
    Create a valid evidence sequence on a disposable engine, verify it, tamper
    with a payload, and verify integrity checking fails.

    Uses a scratch in-memory engine (no append-only guard triggers) so the
    tamper can be written directly, mirroring test_evidence_chain.py.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.base import Base as _Base  # noqa: F401
    from app.models.evidence import (
        EvidenceChainHead,
    )

    engine = create_engine("sqlite:///:memory:")
    EvidenceChainHead.__table__.create(engine)
    EvidenceLogEntry.__table__.create(engine)
    EvidencePayload.__table__.create(engine)
    session = Session(engine)

    try:
        chain = EvidenceChain(session)
        chain.append("login", {"type": "login", "session_id": "s-1"})
        chain.append("payout", {"type": "payout", "amount": 100.0})

        before = chain.verify()
        assert before["valid"] is True

        # Tamper with a disposable test record.
        payload = session.query(EvidencePayload).filter_by(seq=1).first()
        payload.payload = {"type": "tampered", "session_id": "s-1"}
        session.commit()

        after = chain.verify()
        assert after["valid"] is False
        assert after["first_broken_seq"] == 1
    finally:
        session.close()
        engine.dispose()


# ----------------------------------------------------------------------
# Honey / DECOY isolation: decoy payouts never invoke the payment provider
# ----------------------------------------------------------------------


def test_decoy_payout_routes_to_honey_and_never_paypal(
    client: TestClient, db_session: SessionLocal
):
    """
    A DECOY session payout must be served by the honey adapter only. The
    configured payment provider (mock) must not be invoked, and no
    provider_transaction_id from a real provider may be surfaced.

    A stub risk engine returns DECOY so the routing decision is stable and
    independent of behavioural calibration; the real honey adapter is used so
    the synthetic payout + evidence path is exercised end to end.
    """

    from app.gateway.policy import TrustGatewayPolicy
    from app.gateway.provider import get_decoy_provider
    from app.gateway.service import create_gateway_service
    from app.risk.schemas import RiskEvaluationResult

    class StubDecoyEngine:
        def evaluate(self, db, session, request):
            return RiskEvaluationResult(
                decision_id=uuid.uuid4(),
                session_id=session.session_id,
                risk_score=75.0,
                evaluated_trust_level=TrustLevel.DECOY,
                risk_signals={"STUB_DECOY": 75.0},
                reason_codes=["STUB_DECOY_RISK"],
                evaluated_at=datetime.now(timezone.utc),
            )

    # Ensure an active session exists for the caller.
    session = db_session.query(SessionRecord).filter_by(session_id=DECOY_SESSION_ID).first()
    if session is None:
        session = SessionRecord(
            session_id=DECOY_SESSION_ID,
            user_id=TEST_USER_ID,
            merchant_id=TEST_MERCHANT_ID,
            trust_level=TrustLevel.DECOY.value,
            risk_score=75.0,
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        db_session.commit()
    else:
        session.trust_level = TrustLevel.DECOY.value
        session.risk_score = 75.0
        session.status = SessionStatus.ACTIVE.value
        db_session.commit()

    service = create_gateway_service(
        policy=TrustGatewayPolicy(provider_mode="mock"),
        risk_engine=StubDecoyEngine(),
        provider_adapter=mock_provider_instance,
        decoy_adapter=get_decoy_provider(),
    )

    decoy_before = get_decoy_provider().invocation_count
    request = PayoutRequest(
        session_id=DECOY_SESSION_ID,
        recipient_email="offshore@quiet-ledger.example",
        amount=12750.00,
        currency="USD",
        reference_note="decoy-drill",
        idempotency_key="decoy-integration-001",
    )
    principal = AuthenticatedPrincipal(
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        role=RoleEnum.MERCHANT,
        username="merchant@test.com",
    )

    response = service.execute_payout(db=db_session, request=request, principal=principal)

    assert response.action.value == "DECOY_FORWARD"
    assert response.routing_destination.value == "DECOY_HONEY"
    assert response.provider_reference is not None
    assert response.provider_reference.startswith("HONEY-")

    # The honey adapter was invoked; the real (mock) payment provider was not.
    assert get_decoy_provider().invocation_count == decoy_before + 1
    assert mock_provider_instance.invocation_count == 0


# ----------------------------------------------------------------------
# Idempotency: duplicate payouts are not executed twice
# ----------------------------------------------------------------------


def test_duplicate_payout_served_from_cache_no_second_provider_call(
    client: TestClient,
):
    mock_provider_instance.reset()
    idempotency_key = "idemp-integration-" + str(uuid.uuid4())
    payload = {
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "contractor@safe.com",
        "amount": 750.00,
        "currency": "USD",
        "reference_note": "bi-weekly contractor payout",
        "idempotency_key": idempotency_key,
    }

    resp1 = client.post("/v1/payouts", json=payload, headers=_headers())
    assert resp1.status_code == 200, resp1.text
    data1 = resp1.json()
    assert data1["status"] == "completed"
    assert data1["is_duplicate"] is False
    assert mock_provider_instance.invocation_count == 1
    first_ref = data1["provider_reference"]

    # Replay with the identical idempotency key.
    resp2 = client.post("/v1/payouts", json=payload, headers=_headers())
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "completed"
    assert data2["is_duplicate"] is True
    assert data2["provider_reference"] == first_ref

    # The provider must NOT be called a second time.
    assert mock_provider_instance.invocation_count == 1

    # Reset so the autouse teardown also sees a clean counter.
    mock_provider_instance.reset()
