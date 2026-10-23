"""
Regression tests for payout provider provenance.

The Trust Gateway used to hardcode `provider_name="mock"` on every successful
payout record, regardless of which adapter actually executed the payout, and
hardcoded a synthetic decoy label for honey-routed payouts. These tests lock in
the corrected behaviour:

* the persisted identity always names the adapter that executed the payout,
* honey-routed payouts carry the synthetic decoy identity,
* payouts that never reached a provider carry no provider identity,
* risk decisions, session ownership, idempotency and transaction safety are
  unchanged.

No test in this module may execute a real or PayPal sandbox payout: every
adapter is a local test double, and the PayPal Sandbox adapter is actively
disabled by the `forbid_sandbox_payouts` fixture.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.repositories.payout_repo import PayoutRepository
from app.gateway.provider import (
    PROVIDER_NAME_NONE,
    PROVIDER_NAME_UNKNOWN,
    PayPalSandboxAdapter,
    ProviderPayoutResult,
    decoy_provider_instance,
    mock_provider_instance,
)
from app.models.payout import PayoutRequestRecord
from app.models.risk import RiskDecisionRecord
from app.schemas.payouts import PayoutRequest
from tests.conftest import (
    DECOY_SESSION_ID,
    ISOLATED_SESSION_ID,
    NORMAL_SESSION_ID,
    RESTRICTED_SESSION_ID,
)


class RecordingProviderAdapter:
    """
    Test double for a payment provider adapter.

    It never contacts a payment network: it records invocations and returns a
    synthetic ProviderPayoutResult carrying a configurable provider identity.
    """

    def __init__(self, provider_name: str, environment: str = "synthetic_test_double"):
        self.provider_name = provider_name
        self.environment = environment
        self.invocations: list[PayoutRequest] = []

    def execute_payout(self, request: PayoutRequest, merchant_id: UUID) -> ProviderPayoutResult:
        self.invocations.append(request)
        return ProviderPayoutResult(
            success=True,
            provider_name=self.provider_name,
            provider_transaction_id=f"TESTDOUBLE-TXN-{uuid.uuid4().hex[:12].upper()}",
            environment=self.environment,
            details={
                "test_double_warning": "TEST DOUBLE ADAPTER. NO REAL MONEY MOVED.",
                "recipient": request.recipient_email,
                "amount": request.amount,
                "currency": request.currency,
                "merchant_id": str(merchant_id),
            },
            executed_at=datetime.now(timezone.utc),
        )

    def verify_webhook_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        return False


class RecordingDecoyAdapter:
    """
    Test double for the synthetic honey decoy adapter.

    It never contacts a payment network and never moves funds.
    """

    def __init__(
        self,
        provider_name: str = "honey_synthetic_decoy",
        environment: str = "honey_sandbox_simulation",
    ):
        self.provider_name = provider_name
        self.environment = environment
        self.invocations: list[PayoutRequest] = []

    def execute_decoy(self, request: PayoutRequest, merchant_id: UUID) -> ProviderPayoutResult:
        self.invocations.append(request)
        return ProviderPayoutResult(
            success=True,
            provider_name=self.provider_name,
            provider_transaction_id=f"HONEY-TESTDOUBLE-TXN-{uuid.uuid4().hex[:12].upper()}",
            environment=self.environment,
            details={
                "honey_warning": "CONFINEMENT SIMULATION. DECOY WORKSPACE ENGAGED.",
                "recipient": request.recipient_email,
                "amount": request.amount,
                "currency": request.currency,
                "merchant_id": str(merchant_id),
            },
            executed_at=datetime.now(timezone.utc),
        )


@contextmanager
def installed_adapters(provider=None, decoy=None):
    """Install the test doubles as the gateway's provider adapters."""
    with (
        patch(
            "app.gateway.service.get_payment_provider",
            return_value=provider if provider is not None else mock_provider_instance,
        ),
        patch(
            "app.gateway.service.get_decoy_provider",
            return_value=decoy if decoy is not None else decoy_provider_instance,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def forbid_sandbox_payouts():
    """
    Guard rail: no test in this module may reach the PayPal Sandbox adapter
    or perform a real credential exchange.
    """
    with (
        patch.object(
            PayPalSandboxAdapter,
            "execute_payout",
            side_effect=AssertionError("PayPal Sandbox payout execution is forbidden in tests."),
        ),
        patch.object(
            PayPalSandboxAdapter,
            "_get_access_token",
            side_effect=AssertionError("PayPal Sandbox authentication is forbidden in tests."),
        ),
    ):
        yield


def _payout_payload(session_id: UUID, amount: float = 1250.00, idempotency_key: str | None = None):
    return {
        "session_id": str(session_id),
        "recipient_email": "contractor@supplier.com",
        "amount": amount,
        "currency": "USD",
        "reference_note": "Invoice #4021",
        "idempotency_key": idempotency_key or f"provenance-{uuid.uuid4()}",
    }


def _stored_payout(db_session: Session, payout_id: str) -> PayoutRequestRecord:
    record = PayoutRepository(db_session).get_by_id(uuid.UUID(str(payout_id)))
    assert record is not None, "Payout record was not persisted"
    return record


def test_successful_payout_records_the_executing_provider_identity(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    Regression:
    A payout executed by a non-mock adapter must NOT be recorded with the
    hardcoded provider_name "mock". The record must name the adapter that
    actually executed the payout.
    """
    adapter = RecordingProviderAdapter(provider_name="paypal_sandbox", environment="paypal_sandbox")

    with installed_adapters(provider=adapter):
        res = client.post(
            "/v1/payouts",
            json=_payout_payload(NORMAL_SESSION_ID),
            headers=merchant_auth_headers,
        )

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert len(adapter.invocations) == 1

    record = _stored_payout(db_session, data["payout_id"])
    assert record.provider_name == "paypal_sandbox"
    assert record.provider_name != "mock"
    assert record.provider_reference.startswith("TESTDOUBLE-TXN-")


@pytest.mark.parametrize(
    "provider_name,environment",
    [
        ("mock_adapter", "synthetic_mock"),
        ("paypal_sandbox", "paypal_sandbox"),
        ("custom_gateway_adapter", "synthetic_test_double"),
    ],
)
def test_recorded_identity_always_matches_the_executing_adapter(
    client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
    provider_name: str,
    environment: str,
):
    """
    The recorded provider identity is always taken from the adapter result,
    for every adapter identity.
    """
    adapter = RecordingProviderAdapter(provider_name=provider_name, environment=environment)

    with installed_adapters(provider=adapter):
        res = client.post(
            "/v1/payouts",
            json=_payout_payload(NORMAL_SESSION_ID),
            headers=merchant_auth_headers,
        )

    assert res.status_code == 200
    record = _stored_payout(db_session, res.json()["payout_id"])

    assert record.provider_name == provider_name
    assert record.provider_payload["provider_name"] == provider_name
    assert record.provider_payload["provider_environment"] == environment
    assert record.provider_payload["test_double_warning"]


def test_default_mock_adapter_is_recorded_under_its_own_identity(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    The built-in mock adapter declares the identity "mock_adapter"; the record
    must reflect that instead of the generic hardcoded "mock".
    """
    mock_provider_instance.reset()

    res = client.post(
        "/v1/payouts",
        json=_payout_payload(NORMAL_SESSION_ID),
        headers=merchant_auth_headers,
    )

    assert res.status_code == 200
    record = _stored_payout(db_session, res.json()["payout_id"])

    assert record.provider_name == "mock_adapter"
    assert record.provider_name != "mock"
    assert mock_provider_instance.invocation_count == 1


def test_decoy_payout_records_the_synthetic_decoy_identity(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    Honey-routed payouts carry the synthetic decoy identity of the adapter
    that ran them, and never a real/mock payment provider identity.
    """
    mock_provider_instance.reset()

    res = client.post(
        "/v1/payouts",
        json=_payout_payload(DECOY_SESSION_ID, amount=5000.00),
        headers=merchant_auth_headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "decoy_completed"

    record = _stored_payout(db_session, data["payout_id"])
    assert record.provider_name == "honey_synthetic_decoy"
    assert record.provider_name != "mock"
    assert record.provider_payload["provider_environment"] == "honey_sandbox_simulation"
    assert record.provider_reference.startswith("HONEY-DECOY-SIM-TXN-")

    # The real/mock payment provider was never engaged for a decoy.
    assert mock_provider_instance.invocation_count == 0


def test_decoy_identity_follows_the_decoy_adapter_that_ran(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    The decoy identity is resolved from the decoy adapter result, not from a
    hardcoded label.
    """
    decoy = RecordingDecoyAdapter(
        provider_name="honey_synthetic_decoy_v2", environment="honey_sandbox_simulation"
    )

    with installed_adapters(decoy=decoy):
        res = client.post(
            "/v1/payouts",
            json=_payout_payload(DECOY_SESSION_ID, amount=5000.00),
            headers=merchant_auth_headers,
        )

    assert res.status_code == 200
    record = _stored_payout(db_session, res.json()["payout_id"])

    assert record.provider_name == "honey_synthetic_decoy_v2"
    assert len(decoy.invocations) == 1


@pytest.mark.parametrize(
    "session_id,expected_status",
    [
        (RESTRICTED_SESSION_ID, "rejected"),
        (ISOLATED_SESSION_ID, "blocked"),
    ],
)
def test_payouts_that_never_reached_a_provider_record_no_provider(
    client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
    session_id: UUID,
    expected_status: str,
):
    """
    Payouts denied before execution never engaged a provider, so the record
    must carry no provider identity at all.
    """
    mock_provider_instance.reset()

    res = client.post(
        "/v1/payouts",
        json=_payout_payload(session_id, amount=100.00),
        headers=merchant_auth_headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == expected_status

    record = _stored_payout(db_session, data["payout_id"])
    assert record.provider_name == PROVIDER_NAME_NONE
    assert record.provider_reference is None
    assert record.executed_at is None
    assert mock_provider_instance.invocation_count == 0


def test_overlong_provider_identity_is_truncated_but_fully_audited(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    An adapter identity longer than the persisted column width is truncated so
    the write cannot fail after the provider executed, while the full identity
    remains available in the audit payload.
    """
    long_name = "provider-" + ("x" * 40)
    adapter = RecordingProviderAdapter(provider_name=long_name)

    with installed_adapters(provider=adapter):
        res = client.post(
            "/v1/payouts",
            json=_payout_payload(NORMAL_SESSION_ID),
            headers=merchant_auth_headers,
        )

    assert res.status_code == 200
    record = _stored_payout(db_session, res.json()["payout_id"])

    assert len(record.provider_name) == 32
    assert record.provider_name == long_name[:32]
    assert record.provider_payload["provider_name"] == long_name


def test_blank_provider_identity_degrades_to_unknown_provider(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    A blank identity must not be persisted as "none": a provider did execute,
    so claiming that none did would be false provenance.
    """
    adapter = RecordingProviderAdapter(provider_name="   ")

    with installed_adapters(provider=adapter):
        res = client.post(
            "/v1/payouts",
            json=_payout_payload(NORMAL_SESSION_ID),
            headers=merchant_auth_headers,
        )

    assert res.status_code == 200
    record = _stored_payout(db_session, res.json()["payout_id"])

    assert record.provider_name == PROVIDER_NAME_UNKNOWN
    assert record.provider_name != PROVIDER_NAME_NONE


def test_ownership_mismatch_never_reaches_any_adapter(
    client: TestClient, other_merchant_auth_headers: dict
):
    """
    Session ownership enforcement is unchanged: a foreign merchant never
    reaches a provider adapter, whatever the adapter identity would be.
    """
    adapter = RecordingProviderAdapter(provider_name="paypal_sandbox")

    with installed_adapters(provider=adapter):
        res = client.post(
            "/v1/payouts",
            json=_payout_payload(NORMAL_SESSION_ID),
            headers=other_merchant_auth_headers,
        )

    assert res.status_code == 403
    assert res.json()["error"]["code"] == "SESSION_OWNERSHIP_MISMATCH"
    assert adapter.invocations == []


def test_risk_decision_is_preserved_and_linked_to_the_payout(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    Recording provider provenance does not alter the risk decision that was
    persisted for the payout.
    """
    adapter = RecordingProviderAdapter(provider_name="paypal_sandbox")

    with installed_adapters(provider=adapter):
        res = client.post(
            "/v1/payouts",
            json=_payout_payload(NORMAL_SESSION_ID),
            headers=merchant_auth_headers,
        )

    assert res.status_code == 200
    data = res.json()

    record = _stored_payout(db_session, data["payout_id"])
    decision = (
        db_session.query(RiskDecisionRecord)
        .filter_by(decision_id=uuid.UUID(str(data["decision_id"])))
        .one()
    )

    assert record.decision_id == decision.decision_id
    assert decision.action == "ALLOW"
    assert decision.trust_level == "NORMAL"
    assert data["action"] == "ALLOW"
    assert data["trust_level"] == "NORMAL"


def test_duplicate_request_does_not_reexecute_the_adapter(
    client: TestClient, merchant_auth_headers: dict, db_session: Session
):
    """
    Idempotency is unchanged: a replayed request is served from the cached
    response and never reaches the adapter a second time.
    """
    adapter = RecordingProviderAdapter(provider_name="paypal_sandbox")
    payload = _payout_payload(NORMAL_SESSION_ID)

    with installed_adapters(provider=adapter):
        res1 = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
        res2 = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res2.json()["is_duplicate"] is True
    assert res2.json()["provider_reference"] == res1.json()["provider_reference"]
    assert len(adapter.invocations) == 1

    record = _stored_payout(db_session, res1.json()["payout_id"])
    assert record.provider_name == "paypal_sandbox"


def test_post_provider_failure_keeps_the_reconciliation_guard(
    client: TestClient, merchant_auth_headers: dict
):
    """
    Transaction safety is unchanged: if the database fails after the provider
    executed, the idempotency record is parked in 'provider_executed' and a
    retry is refused instead of double-executing the payout.
    """
    adapter = RecordingProviderAdapter(provider_name="paypal_sandbox")
    payload = _payout_payload(NORMAL_SESSION_ID)
    client_no_raise = TestClient(client.app, raise_server_exceptions=False)

    with (
        installed_adapters(provider=adapter),
        patch(
            "app.db.repositories.payout_repo.PayoutRepository.create",
            side_effect=RuntimeError("Simulated Database Disk Failure During Payout Persistence"),
        ),
    ):
        res1 = client_no_raise.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
        assert res1.status_code == 500

    assert len(adapter.invocations) == 1

    with installed_adapters(provider=adapter):
        res2 = client_no_raise.post("/v1/payouts", json=payload, headers=merchant_auth_headers)

    assert res2.status_code == 403
    assert res2.json()["error"]["code"] == "PAYOUT_ALREADY_EXECUTED_RECONCILIATION_REQUIRED"
    assert len(adapter.invocations) == 1


def test_sandbox_adapter_is_never_executed_by_the_gateway(
    client: TestClient, merchant_auth_headers: dict
):
    """
    The gateway route exercised here never reaches the PayPal Sandbox adapter:
    no real or sandbox payout is executed by the test suite.
    """
    with patch.object(PayPalSandboxAdapter, "execute_payout") as sandbox_execute:
        res = client.post(
            "/v1/payouts",
            json=_payout_payload(NORMAL_SESSION_ID),
            headers=merchant_auth_headers,
        )

    assert res.status_code == 200
    sandbox_execute.assert_not_called()
