"""
Trust Gateway routing, policy and transaction-safety tests.

These tests exercise the gateway service (app/gateway/service.py) and the
centralized routing policy (app/gateway/policy.py) directly, with a
deterministic risk-engine double. Person 2's risk model is never modified or
re-implemented here: the double only replaces the *decision input* so that
routing outcomes are stable and independent of behavioural calibration.

Covered invariants:
  * NORMAL requests may call the configured provider (mock or PayPal Sandbox),
  * RESTRICTED requests never reach PayPal and require the configured
    restriction / step-up behaviour,
  * DECOY requests are served by the honey adapter only,
  * ISOLATED requests are blocked without any provider execution,
  * session ownership and session state enforcement,
  * idempotency: duplicates, payload conflicts and in-flight requests,
  * provider failure handling, including the ambiguous timeout outcome that
    must never be retried blindly.

SAFETY: the PayPal Sandbox adapter is always wired to an httpx.MockTransport
against a reserved ".test" host, so no test in this module can contact PayPal.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    DuplicateRequestException,
    IdentityTwinException,
    OwnershipMismatchException,
    PaymentProviderException,
    PolicyViolationException,
    ProviderTimeoutException,
)
from app.core.security import AuthenticatedPrincipal, RoleEnum
from app.gateway.policy import TrustGatewayPolicy, get_gateway_policy
from app.gateway.provider import (
    PROVIDER_NAME_NONE,
    DecoyHoneyAdapter,
    PayPalSandboxAdapter,
    ProviderPayoutResult,
)
from app.gateway.service import TrustGatewayService, create_gateway_service
from app.models.idempotency import IdempotencyRecord
from app.models.incident import IncidentRecord
from app.models.payout import PayoutRequestRecord
from app.models.session import SessionRecord
from app.models.step_up import StepUpChallenge
from app.risk.schemas import RiskEvaluationRequest, RiskEvaluationResult
from app.schemas.payouts import GatewayAction, PayoutRequest, RoutingDestination
from app.schemas.sessions import SessionStatus, TrustLevel
from tests.conftest import (
    DECOY_SESSION_ID,
    ISOLATED_SESSION_ID,
    NORMAL_SESSION_ID,
    OTHER_MERCHANT_ID,
    RESTRICTED_SESSION_ID,
    TEST_MERCHANT_ID,
    TEST_USER_ID,
)

FAKE_PAYPAL_BASE_URL = "https://paypal-sandbox.test"


# ----------------------------------------------------------------------
# Deterministic test doubles
# ----------------------------------------------------------------------


class StubRiskEngine:
    """
    Deterministic risk-engine double.

    It returns a fixed decision so that gateway routing can be asserted
    without depending on the behavioural twin calibration.
    """

    def __init__(
        self,
        trust_level: TrustLevel,
        risk_score: float,
        reason_codes: list[str] | None = None,
    ):
        self.trust_level = trust_level
        self.risk_score = risk_score
        self.reason_codes = reason_codes or [f"STUB_{trust_level.value}_RISK"]
        self.requests: list[RiskEvaluationRequest] = []

    def evaluate(
        self, db: Session, session: SessionRecord, request: RiskEvaluationRequest
    ) -> RiskEvaluationResult:
        self.requests.append(request)
        return RiskEvaluationResult(
            decision_id=uuid.uuid4(),
            session_id=session.session_id,
            risk_score=self.risk_score,
            evaluated_trust_level=self.trust_level,
            risk_signals={"STUB_RISK_SIGNAL": self.risk_score},
            reason_codes=list(self.reason_codes),
            evaluated_at=datetime.now(timezone.utc),
        )


class RecordingProviderAdapter:
    """Payment provider double that records every invocation."""

    def __init__(
        self, provider_name: str = "stub_provider", environment: str = "synthetic_test_double"
    ):
        self.provider_name = provider_name
        self.environment = environment
        self.invocations: list[tuple[PayoutRequest, uuid.UUID]] = []
        self.error: Exception | None = None
        self.success = True
        self.transaction_id = "STUB-TXN-0001"

    def execute_payout(
        self, request: PayoutRequest, merchant_id: uuid.UUID
    ) -> ProviderPayoutResult:
        self.invocations.append((request, merchant_id))
        if self.error is not None:
            raise self.error
        return ProviderPayoutResult(
            success=self.success,
            provider_name=self.provider_name,
            provider_transaction_id=self.transaction_id,
            environment=self.environment,
            details={
                "stub_warning": "STUB ADAPTER. NO REAL MONEY MOVED.",
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
    """Honey decoy double that records every invocation."""

    def __init__(self, provider_name: str = "honey_synthetic_decoy"):
        self.provider_name = provider_name
        self.invocations: list[tuple[PayoutRequest, uuid.UUID]] = []

    def execute_decoy(self, request: PayoutRequest, merchant_id: uuid.UUID) -> ProviderPayoutResult:
        self.invocations.append((request, merchant_id))
        return ProviderPayoutResult(
            success=True,
            provider_name=self.provider_name,
            provider_transaction_id=f"HONEY-STUB-TXN-{uuid.uuid4().hex[:8].upper()}",
            environment="honey_sandbox_simulation",
            details={
                "honey_warning": "CONFINEMENT SIMULATION. DECOY WORKSPACE ENGAGED.",
                "recipient": request.recipient_email,
                "amount": request.amount,
                "currency": request.currency,
                "merchant_id": str(merchant_id),
            },
            executed_at=datetime.now(timezone.utc),
        )


class PayPalTransportStub:
    """
    httpx transport double for the PayPal Sandbox adapter.

    Only the OAuth token and payouts endpoints are served; any other request
    is a test failure. Because httpx.MockTransport is used, no socket is ever
    opened and PayPal is never contacted.
    """

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200, json={"access_token": "STUB-ACCESS-TOKEN", "expires_in": 3600}
            )
        if request.url.path == "/v1/payments/payouts":
            return httpx.Response(
                201,
                json={
                    "batch_header": {
                        "payout_batch_id": "STUB-PAYOUT-BATCH-1",
                        "batch_status": "PENDING",
                    }
                },
            )
        raise AssertionError(f"Unexpected PayPal request: {request.method} {request.url}")

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def make_paypal_adapter(stub: PayPalTransportStub) -> PayPalSandboxAdapter:
    return PayPalSandboxAdapter(
        client_id="stub-client-id",
        client_secret="stub-client-secret",
        base_url=FAKE_PAYPAL_BASE_URL,
        timeout=5.0,
        transport=stub.transport,
    )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def make_principal(merchant_id: uuid.UUID = TEST_MERCHANT_ID) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=TEST_USER_ID,
        merchant_id=merchant_id,
        role=RoleEnum.MERCHANT,
        username="merchant@test.com",
    )


def make_request(
    session_id: uuid.UUID,
    amount: float = 100.0,
    idempotency_key: str | None = None,
    step_up_token: str | None = None,
) -> PayoutRequest:
    return PayoutRequest(
        session_id=session_id,
        recipient_email="contractor@supplier.com",
        amount=amount,
        currency="USD",
        reference_note="Invoice #4021",
        idempotency_key=idempotency_key or f"gw-{uuid.uuid4()}",
        step_up_token=step_up_token,
    )


def build_service(
    risk_engine: StubRiskEngine,
    provider: RecordingProviderAdapter | PayPalSandboxAdapter | None = None,
    decoy: RecordingDecoyAdapter | DecoyHoneyAdapter | None = None,
    provider_mode: str = "mock",
) -> TrustGatewayService:
    return TrustGatewayService(
        policy=TrustGatewayPolicy(provider_mode=provider_mode),
        risk_engine=risk_engine,
        provider_adapter=provider if provider is not None else RecordingProviderAdapter(),
        decoy_adapter=decoy if decoy is not None else RecordingDecoyAdapter(),
    )


def create_verified_step_up(
    db_session: Session,
    session_id: uuid.UUID,
    merchant_id: uuid.UUID = TEST_MERCHANT_ID,
) -> StepUpChallenge:
    """Create a server-issued, verified and unconsumed step-up challenge."""
    now = datetime.now(timezone.utc)
    challenge = StepUpChallenge(
        session_id=session_id,
        merchant_id=merchant_id,
        code_hash="stub-code-hash",
        expires_at=now + timedelta(minutes=5),
        verified_at=now,
    )
    db_session.add(challenge)
    db_session.commit()
    db_session.refresh(challenge)
    return challenge


def idempotency_record(
    db_session: Session,
    idempotency_key: str,
    merchant_id: uuid.UUID = TEST_MERCHANT_ID,
) -> IdempotencyRecord | None:
    return (
        db_session.query(IdempotencyRecord)
        .filter_by(merchant_id=merchant_id, idempotency_key=idempotency_key)
        .one_or_none()
    )


def request_fingerprint(
    recipient_email: str = "contractor@supplier.com",
    amount: float = 100.0,
    currency: str = "USD",
) -> str:
    """The idempotency fingerprint the gateway stores for a payout request."""
    import hashlib

    return hashlib.sha256(f"{recipient_email}:{amount}:{currency}".encode()).hexdigest()


def payouts_for_key(db_session: Session, idempotency_key: str) -> list[PayoutRequestRecord]:
    return db_session.query(PayoutRequestRecord).filter_by(idempotency_key=idempotency_key).all()


def make_risk_result(
    session_id: uuid.UUID = NORMAL_SESSION_ID,
    trust_level: TrustLevel = TrustLevel.NORMAL,
    risk_score: float = 5.0,
) -> RiskEvaluationResult:
    return RiskEvaluationResult(
        decision_id=uuid.uuid4(),
        session_id=session_id,
        risk_score=risk_score,
        evaluated_trust_level=trust_level,
        risk_signals={},
        reason_codes=[],
        evaluated_at=datetime.now(timezone.utc),
    )


# ----------------------------------------------------------------------
# Routing consistency: policy and adapter share one live decision
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider_mode,expected_destination",
    [
        ("mock", RoutingDestination.PROVIDER_MOCK),
        ("paypal_sandbox", RoutingDestination.PROVIDER_PAYPAL),
    ],
)
def test_gateway_policy_tracks_the_current_provider_configuration(
    monkeypatch, provider_mode: str, expected_destination: RoutingDestination
):
    """
    Regression:
    The policy used to be constructed once at import with the then-current
    provider. A later configuration change switched the adapter while the
    policy kept reporting the old routing destination.
    """
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", provider_mode)

    policy = get_gateway_policy()
    decision = policy.evaluate(make_risk_result())

    assert policy.provider_mode == provider_mode
    assert decision.routing_destination == expected_destination


def test_gateway_policy_rejects_an_unknown_runtime_provider(monkeypatch):
    """A runtime configuration mutation to an unknown value fails closed."""
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "stripe")

    with pytest.raises(IdentityTwinException) as excinfo:
        get_gateway_policy()

    assert excinfo.value.code == "PAYMENT_PROVIDER_UNKNOWN"
    assert excinfo.value.status_code == 500


@pytest.mark.parametrize(
    "provider_mode,expected_destination,adapter_name",
    [
        ("mock", RoutingDestination.PROVIDER_MOCK, "mock_adapter"),
        ("paypal_sandbox", RoutingDestination.PROVIDER_PAYPAL, "paypal_sandbox"),
    ],
)
def test_gateway_service_derives_policy_and_adapter_from_one_runtime_decision(
    db_session: Session,
    monkeypatch,
    provider_mode: str,
    expected_destination: RoutingDestination,
    adapter_name: str,
):
    """
    Regression:
    The service must resolve the policy and the adapter from the same live
    provider mode, so the reported routing destination always names the
    adapter that actually executed the payout.
    """
    provider = RecordingProviderAdapter(provider_name=adapter_name, environment=provider_mode)
    resolved_modes: list[str | None] = []

    def fake_get_payment_provider(provider_name: str | None = None):
        resolved_modes.append(provider_name)
        return provider

    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", provider_mode)
    monkeypatch.setattr(
        "app.gateway.service.get_payment_provider",
        fake_get_payment_provider,
    )
    monkeypatch.setattr(
        "app.gateway.service.get_decoy_provider",
        lambda: RecordingDecoyAdapter(),
    )

    service = create_gateway_service(risk_engine=StubRiskEngine(TrustLevel.NORMAL, 5.0))
    key = f"gw-consistency-{provider_mode}-0001"

    response = service.execute_payout(
        db=db_session,
        request=make_request(NORMAL_SESSION_ID, idempotency_key=key),
        principal=make_principal(),
    )

    assert response.routing_destination == expected_destination
    assert resolved_modes == [provider_mode]
    assert len(provider.invocations) == 1
    assert payouts_for_key(db_session, key)[0].provider_name == adapter_name


@pytest.mark.parametrize(
    "session_id,trust_level,risk_score,expected_status,expected_destination",
    [
        (
            RESTRICTED_SESSION_ID,
            TrustLevel.RESTRICTED,
            45.0,
            "rejected",
            RoutingDestination.RESTRICTED_REJECT,
        ),
        (
            DECOY_SESSION_ID,
            TrustLevel.DECOY,
            75.0,
            "decoy_completed",
            RoutingDestination.DECOY_HONEY,
        ),
        (
            ISOLATED_SESSION_ID,
            TrustLevel.ISOLATED,
            95.0,
            "blocked",
            RoutingDestination.ISOLATED_BLOCK,
        ),
    ],
)
def test_non_normal_states_never_invoke_the_configured_paypal_provider(
    db_session: Session,
    monkeypatch,
    session_id: uuid.UUID,
    trust_level: TrustLevel,
    risk_score: float,
    expected_status: str,
    expected_destination: RoutingDestination,
):
    """
    Even when PayPal Sandbox is the live provider, RESTRICTED, DECOY and
    ISOLATED requests must not reach it.
    """
    provider = RecordingProviderAdapter(provider_name="paypal_sandbox")
    decoy = RecordingDecoyAdapter()
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "paypal_sandbox")

    service = create_gateway_service(
        risk_engine=StubRiskEngine(trust_level, risk_score),
        provider_adapter=provider,
        decoy_adapter=decoy,
    )

    response = service.execute_payout(
        db=db_session,
        request=make_request(session_id),
        principal=make_principal(),
    )

    assert response.status == expected_status
    assert response.routing_destination == expected_destination
    assert provider.invocations == []
    assert len(decoy.invocations) == (
        1 if expected_destination == RoutingDestination.DECOY_HONEY else 0
    )


# ----------------------------------------------------------------------
# NORMAL: the configured provider may be called
# ----------------------------------------------------------------------


def test_normal_request_may_call_the_configured_provider(db_session: Session):
    """A NORMAL session may execute the payout on the configured provider."""
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)

    response = service.execute_payout(
        db=db_session,
        request=make_request(NORMAL_SESSION_ID, amount=1250.00),
        principal=make_principal(),
    )

    assert response.status == "completed"
    assert response.action == GatewayAction.ALLOW
    assert response.trust_level == TrustLevel.NORMAL
    assert response.routing_destination == RoutingDestination.PROVIDER_MOCK
    assert response.provider_reference == provider.transaction_id

    assert len(provider.invocations) == 1
    invoked_request, invoked_merchant = provider.invocations[0]
    assert invoked_request.amount == 1250.00
    assert invoked_merchant == TEST_MERCHANT_ID


def test_normal_request_records_the_executing_provider_identity(db_session: Session):
    """The persisted payout record names the adapter that actually executed it."""
    provider = RecordingProviderAdapter(
        provider_name="paypal_sandbox", environment="paypal_sandbox"
    )
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)
    key = "gw-normal-identity-0001"

    response = service.execute_payout(
        db=db_session,
        request=make_request(NORMAL_SESSION_ID, idempotency_key=key),
        principal=make_principal(),
    )

    records = payouts_for_key(db_session, key)
    assert len(records) == 1
    assert records[0].provider_name == "paypal_sandbox"
    assert records[0].provider_reference == provider.transaction_id
    assert records[0].status == "completed"
    assert records[0].executed_at is not None
    assert records[0].decision_id == response.decision_id


def test_normal_request_may_call_the_configured_paypal_provider(db_session: Session):
    """When PayPal Sandbox is the configured provider, NORMAL may reach it."""
    stub = PayPalTransportStub()
    service = build_service(
        StubRiskEngine(TrustLevel.NORMAL, 5.0),
        provider=make_paypal_adapter(stub),
        provider_mode="paypal_sandbox",
    )
    key = "gw-normal-paypal-0001"

    response = service.execute_payout(
        db=db_session,
        request=make_request(NORMAL_SESSION_ID, idempotency_key=key),
        principal=make_principal(),
    )

    assert response.status == "completed"
    assert response.routing_destination == RoutingDestination.PROVIDER_PAYPAL
    assert response.provider_reference == "STUB-PAYOUT-BATCH-1"
    assert stub.paths() == ["/v1/oauth2/token", "/v1/payments/payouts"]

    records = payouts_for_key(db_session, key)
    assert records[0].provider_name == "paypal_sandbox"


# ----------------------------------------------------------------------
# RESTRICTED: never PayPal, restriction / step-up behaviour required
# ----------------------------------------------------------------------


def test_restricted_request_cannot_call_paypal(db_session: Session):
    """
    A RESTRICTED session without a verified step-up proof never reaches
    PayPal - not even for an OAuth token.
    """
    stub = PayPalTransportStub()
    service = build_service(
        StubRiskEngine(TrustLevel.RESTRICTED, 45.0),
        provider=make_paypal_adapter(stub),
        provider_mode="paypal_sandbox",
    )

    response = service.execute_payout(
        db=db_session,
        request=make_request(RESTRICTED_SESSION_ID, amount=250.00),
        principal=make_principal(),
    )

    assert response.status == "rejected"
    assert response.action == GatewayAction.REQUIRE_STEP_UP
    assert response.routing_destination == RoutingDestination.RESTRICTED_REJECT
    assert response.provider_reference is None
    assert "POLICY_ENFORCED_STEP_UP_CHALLENGE_REQUIRED" in response.reason_codes
    assert stub.requests == []


def test_restricted_request_does_not_call_the_payment_provider(db_session: Session):
    """The same holds for the built-in provider adapter."""
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.RESTRICTED, 45.0), provider=provider)

    response = service.execute_payout(
        db=db_session,
        request=make_request(RESTRICTED_SESSION_ID, amount=250.00),
        principal=make_principal(),
    )

    assert response.status == "rejected"
    assert provider.invocations == []


def test_restricted_request_above_the_payout_limit_is_rejected_even_with_step_up(
    db_session: Session,
):
    """The restricted payout limit is a hard cap, independent of step-up proof."""
    challenge = create_verified_step_up(db_session, RESTRICTED_SESSION_ID)
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.RESTRICTED, 45.0), provider=provider)

    response = service.execute_payout(
        db=db_session,
        request=make_request(
            RESTRICTED_SESSION_ID,
            amount=900.00,
            step_up_token=str(challenge.id),
        ),
        principal=make_principal(),
    )

    assert response.status == "rejected"
    assert response.action == GatewayAction.REQUIRE_STEP_UP
    assert "RESTRICTED_PAYOUT_LIMIT_EXCEEDED" in response.reason_codes
    assert provider.invocations == []


def test_restricted_request_with_verified_step_up_uses_the_configured_provider(
    db_session: Session,
):
    """
    A verified, unconsumed step-up proof lifts the restriction and the payout
    is executed on the configured provider. The challenge is single use.
    """
    challenge = create_verified_step_up(db_session, RESTRICTED_SESSION_ID)
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.RESTRICTED, 45.0), provider=provider)

    response = service.execute_payout(
        db=db_session,
        request=make_request(
            RESTRICTED_SESSION_ID,
            amount=200.00,
            step_up_token=str(challenge.id),
        ),
        principal=make_principal(),
    )

    assert response.status == "completed"
    assert response.action == GatewayAction.ALLOW
    assert "RESTRICTED_STEP_UP_VERIFIED_PAYOUT_PERMITTED" in response.reason_codes
    assert len(provider.invocations) == 1

    db_session.refresh(challenge)
    assert challenge.used_at is not None


def test_restricted_request_with_a_forged_step_up_token_is_rejected(db_session: Session):
    """An unverifiable step-up token never unlocks the provider."""
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.RESTRICTED, 45.0), provider=provider)

    response = service.execute_payout(
        db=db_session,
        request=make_request(
            RESTRICTED_SESSION_ID,
            amount=200.00,
            step_up_token=str(uuid.uuid4()),
        ),
        principal=make_principal(),
    )

    assert response.status == "rejected"
    assert provider.invocations == []


def test_restricted_request_with_a_consumed_step_up_token_is_rejected(db_session: Session):
    """A step-up proof is single use: it cannot be replayed for a second payout."""
    challenge = create_verified_step_up(db_session, RESTRICTED_SESSION_ID)
    challenge.used_at = datetime.now(timezone.utc)
    db_session.commit()

    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.RESTRICTED, 45.0), provider=provider)

    response = service.execute_payout(
        db=db_session,
        request=make_request(
            RESTRICTED_SESSION_ID,
            amount=200.00,
            step_up_token=str(challenge.id),
        ),
        principal=make_principal(),
    )

    assert response.status == "rejected"
    assert provider.invocations == []


# ----------------------------------------------------------------------
# DECOY: honey adapter only
# ----------------------------------------------------------------------


def test_decoy_request_uses_only_the_honey_adapter(db_session: Session):
    """A DECOY session is served by the honey workspace, never by a provider."""
    provider = RecordingProviderAdapter()
    decoy = RecordingDecoyAdapter()
    service = build_service(StubRiskEngine(TrustLevel.DECOY, 75.0), provider=provider, decoy=decoy)

    response = service.execute_payout(
        db=db_session,
        request=make_request(DECOY_SESSION_ID, amount=5000.00),
        principal=make_principal(),
    )

    assert response.status == "decoy_completed"
    assert response.action == GatewayAction.DECOY_FORWARD
    assert response.routing_destination == RoutingDestination.DECOY_HONEY
    assert response.provider_reference.startswith("HONEY-STUB-TXN-")

    assert provider.invocations == []
    assert len(decoy.invocations) == 1


def test_decoy_request_never_contacts_paypal(db_session: Session):
    """The honey path must not open a PayPal connection, not even for a token."""
    stub = PayPalTransportStub()
    service = build_service(
        StubRiskEngine(TrustLevel.DECOY, 75.0),
        provider=make_paypal_adapter(stub),
        provider_mode="paypal_sandbox",
    )

    response = service.execute_payout(
        db=db_session,
        request=make_request(DECOY_SESSION_ID, amount=5000.00),
        principal=make_principal(),
    )

    assert response.status == "decoy_completed"
    assert stub.requests == []


def test_decoy_payout_is_recorded_with_the_honey_identity(db_session: Session):
    """The audit trail names the honey adapter, never a payment provider."""
    decoy = RecordingDecoyAdapter(provider_name="honey_synthetic_decoy_v2")
    service = build_service(
        StubRiskEngine(TrustLevel.DECOY, 75.0),
        provider=RecordingProviderAdapter(),
        decoy=decoy,
    )
    key = "gw-decoy-identity-0001"

    service.execute_payout(
        db=db_session,
        request=make_request(DECOY_SESSION_ID, idempotency_key=key),
        principal=make_principal(),
    )

    records = payouts_for_key(db_session, key)
    assert len(records) == 1
    assert records[0].provider_name == "honey_synthetic_decoy_v2"
    assert records[0].status == "decoy_completed"


# ----------------------------------------------------------------------
# ISOLATED: blocked, no provider execution
# ----------------------------------------------------------------------


def test_isolated_request_is_blocked_without_provider_execution(db_session: Session):
    """An ISOLATED session is blocked: no provider and no honey execution."""
    provider = RecordingProviderAdapter()
    decoy = RecordingDecoyAdapter()
    service = build_service(
        StubRiskEngine(TrustLevel.ISOLATED, 95.0), provider=provider, decoy=decoy
    )

    response = service.execute_payout(
        db=db_session,
        request=make_request(ISOLATED_SESSION_ID, amount=9999.00),
        principal=make_principal(),
    )

    assert response.status == "blocked"
    assert response.action == GatewayAction.BLOCK
    assert response.routing_destination == RoutingDestination.ISOLATED_BLOCK
    assert response.provider_reference is None
    assert provider.invocations == []
    assert decoy.invocations == []


def test_isolated_request_never_contacts_paypal(db_session: Session):
    """A blocked request must not open a PayPal connection."""
    stub = PayPalTransportStub()
    service = build_service(
        StubRiskEngine(TrustLevel.ISOLATED, 95.0),
        provider=make_paypal_adapter(stub),
        provider_mode="paypal_sandbox",
    )

    response = service.execute_payout(
        db=db_session,
        request=make_request(ISOLATED_SESSION_ID, amount=9999.00),
        principal=make_principal(),
    )

    assert response.status == "blocked"
    assert stub.requests == []


def test_isolated_request_is_recorded_without_a_provider_identity(db_session: Session):
    """A blocked payout never claims that a provider executed it."""
    service = build_service(StubRiskEngine(TrustLevel.ISOLATED, 95.0))
    key = "gw-isolated-identity-0001"

    service.execute_payout(
        db=db_session,
        request=make_request(ISOLATED_SESSION_ID, idempotency_key=key),
        principal=make_principal(),
    )

    records = payouts_for_key(db_session, key)
    assert len(records) == 1
    assert records[0].provider_name == PROVIDER_NAME_NONE
    assert records[0].provider_reference is None
    assert records[0].executed_at is None


def test_isolated_request_isolates_the_session_and_opens_an_incident(db_session: Session):
    """Blocking a payout escalates to session isolation and an incident."""
    service = build_service(StubRiskEngine(TrustLevel.ISOLATED, 95.0))

    service.execute_payout(
        db=db_session,
        request=make_request(ISOLATED_SESSION_ID, amount=9999.00),
        principal=make_principal(),
    )

    session = db_session.query(SessionRecord).filter_by(session_id=ISOLATED_SESSION_ID).one()
    assert session.status == SessionStatus.REVOKED.value

    incident = (
        db_session.query(IncidentRecord)
        .filter_by(session_id=ISOLATED_SESSION_ID)
        .order_by(IncidentRecord.created_at.desc())
        .first()
    )
    assert incident is not None
    assert incident.severity == "CRITICAL"
    assert incident.status == "OPEN"


# ----------------------------------------------------------------------
# Session ownership and session state
# ----------------------------------------------------------------------


def test_foreign_session_never_reaches_the_provider(db_session: Session):
    """A session owned by another merchant is refused before any execution."""
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)

    with pytest.raises(OwnershipMismatchException) as excinfo:
        service.execute_payout(
            db=db_session,
            request=make_request(NORMAL_SESSION_ID),
            principal=make_principal(merchant_id=OTHER_MERCHANT_ID),
        )

    assert excinfo.value.status_code == 403
    assert provider.invocations == []


def test_inactive_session_never_reaches_the_provider(db_session: Session):
    """A revoked session cannot execute a payout."""
    session = db_session.query(SessionRecord).filter_by(session_id=NORMAL_SESSION_ID).one()
    session.status = SessionStatus.REVOKED.value
    db_session.commit()

    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)

    with pytest.raises(PolicyViolationException) as excinfo:
        service.execute_payout(
            db=db_session,
            request=make_request(NORMAL_SESSION_ID),
            principal=make_principal(),
        )

    assert excinfo.value.code == "INACTIVE_SESSION"
    assert provider.invocations == []


def test_expired_session_never_reaches_the_provider(db_session: Session):
    """An expired session cannot execute a payout."""
    session = db_session.query(SessionRecord).filter_by(session_id=NORMAL_SESSION_ID).one()
    session.status = SessionStatus.EXPIRED.value
    db_session.commit()

    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)

    with pytest.raises(PolicyViolationException) as excinfo:
        service.execute_payout(
            db=db_session,
            request=make_request(NORMAL_SESSION_ID),
            principal=make_principal(),
        )

    assert excinfo.value.code == "INACTIVE_SESSION"
    assert provider.invocations == []


def test_unknown_session_is_not_found(db_session: Session):
    """An unknown session id never reaches the provider."""
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)

    from app.core.exceptions import EntityNotFoundException

    with pytest.raises(EntityNotFoundException):
        service.execute_payout(
            db=db_session,
            request=make_request(uuid.uuid4()),
            principal=make_principal(),
        )

    assert provider.invocations == []


# ----------------------------------------------------------------------
# Idempotency
# ----------------------------------------------------------------------


def test_duplicate_idempotency_key_is_served_from_the_cache(db_session: Session):
    """A replayed request never reaches the provider a second time."""
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)
    key = "gw-duplicate-0001"
    request = make_request(NORMAL_SESSION_ID, idempotency_key=key)

    first = service.execute_payout(db=db_session, request=request, principal=make_principal())
    second = service.execute_payout(db=db_session, request=request, principal=make_principal())

    assert first.status == "completed"
    assert second.status == "completed"
    assert second.is_duplicate is True
    assert second.payout_id == first.payout_id
    assert second.provider_reference == first.provider_reference
    assert len(provider.invocations) == 1


def test_duplicate_idempotency_key_with_a_conflicting_payload_is_rejected(
    db_session: Session,
):
    """Reusing a key with a different amount is an idempotency violation."""
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)
    key = "gw-conflict-0001"

    service.execute_payout(
        db=db_session,
        request=make_request(NORMAL_SESSION_ID, amount=100.00, idempotency_key=key),
        principal=make_principal(),
    )

    with pytest.raises(PolicyViolationException) as excinfo:
        service.execute_payout(
            db=db_session,
            request=make_request(NORMAL_SESSION_ID, amount=900.00, idempotency_key=key),
            principal=make_principal(),
        )

    assert excinfo.value.code == "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"
    assert len(provider.invocations) == 1


def test_duplicate_idempotency_key_with_a_conflicting_recipient_is_rejected(
    db_session: Session,
):
    """The idempotency fingerprint covers the recipient as well as the amount."""
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)
    key = "gw-conflict-0002"

    service.execute_payout(
        db=db_session,
        request=make_request(NORMAL_SESSION_ID, idempotency_key=key),
        principal=make_principal(),
    )

    conflicting = make_request(NORMAL_SESSION_ID, idempotency_key=key)
    conflicting.recipient_email = "attacker@elsewhere.com"

    with pytest.raises(PolicyViolationException) as excinfo:
        service.execute_payout(db=db_session, request=conflicting, principal=make_principal())

    assert excinfo.value.code == "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"
    assert len(provider.invocations) == 1


def test_idempotency_key_that_is_still_processing_is_refused(db_session: Session):
    """An in-flight key is refused with a conflict, without a second execution."""
    provider = RecordingProviderAdapter()
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)
    key = "gw-inflight-0001"

    record = IdempotencyRecord(
        idempotency_key=key,
        merchant_id=TEST_MERCHANT_ID,
        request_hash=request_fingerprint(),
        status="processing",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(record)
    db_session.commit()

    with pytest.raises(DuplicateRequestException) as excinfo:
        service.execute_payout(
            db=db_session,
            request=make_request(NORMAL_SESSION_ID, idempotency_key=key),
            principal=make_principal(),
        )

    assert excinfo.value.code == "IDEMPOTENCY_IN_PROGRESS"
    assert excinfo.value.status_code == 409
    assert provider.invocations == []


# ----------------------------------------------------------------------
# Provider failures
# ----------------------------------------------------------------------


def test_provider_failure_is_propagated_and_persists_no_completed_payout(db_session: Session):
    """A definite provider failure surfaces to the caller and is not recorded."""
    provider = RecordingProviderAdapter()
    provider.error = PaymentProviderException(
        message="PayPal Sandbox payout rejected.", code="PAYPAL_PAYOUT_REJECTED"
    )
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)
    key = "gw-provider-failure-0001"

    with pytest.raises(PaymentProviderException) as excinfo:
        service.execute_payout(
            db=db_session,
            request=make_request(NORMAL_SESSION_ID, idempotency_key=key),
            principal=make_principal(),
        )

    assert excinfo.value.code == "PAYPAL_PAYOUT_REJECTED"
    assert len(provider.invocations) == 1
    assert payouts_for_key(db_session, key) == []


def test_definitive_provider_failure_allows_a_safe_retry(db_session: Session):
    """
    A failure that provably moved no funds leaves the key retryable.

    The retry must not be rejected by the idempotency store: the key is
    reused, not duplicated.
    """
    provider = RecordingProviderAdapter()
    provider.error = PaymentProviderException(
        message="PayPal Sandbox payout rejected.", code="PAYPAL_PAYOUT_REJECTED"
    )
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)
    key = "gw-provider-retry-0001"
    request = make_request(NORMAL_SESSION_ID, idempotency_key=key)

    with pytest.raises(PaymentProviderException):
        service.execute_payout(db=db_session, request=request, principal=make_principal())

    record = idempotency_record(db_session, key)
    assert record is not None
    assert record.status == "failed"

    provider.error = None
    provider.transaction_id = "STUB-TXN-RETRY"
    response = service.execute_payout(db=db_session, request=request, principal=make_principal())

    assert response.status == "completed"
    assert response.provider_reference == "STUB-TXN-RETRY"
    assert len(provider.invocations) == 2

    record = idempotency_record(db_session, key)
    assert record.status == "completed"


def test_ambiguous_provider_timeout_requires_reconciliation_and_refuses_a_retry(
    db_session: Session,
):
    """
    A provider timeout has an ambiguous outcome.

    The key is parked for reconciliation so that a blind retry can never
    double-execute the payout.
    """
    provider = RecordingProviderAdapter()
    provider.error = ProviderTimeoutException(
        message="PayPal Sandbox payout request timed out.", code="PAYPAL_PAYOUT_TIMEOUT"
    )
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)
    key = "gw-provider-timeout-0001"
    request = make_request(NORMAL_SESSION_ID, idempotency_key=key)

    with pytest.raises(ProviderTimeoutException):
        service.execute_payout(db=db_session, request=request, principal=make_principal())

    record = idempotency_record(db_session, key)
    assert record is not None
    assert record.status == "provider_executed"
    assert record.response_payload["error"] == (
        "PROVIDER_OUTCOME_AMBIGUOUS_RECONCILIATION_REQUIRED"
    )
    assert record.response_payload["idempotency_key"] == key

    provider.error = None
    with pytest.raises(PolicyViolationException) as excinfo:
        service.execute_payout(db=db_session, request=request, principal=make_principal())

    assert excinfo.value.code == "PAYOUT_ALREADY_EXECUTED_RECONCILIATION_REQUIRED"
    assert len(provider.invocations) == 1


def test_provider_reporting_an_unsuccessful_execution_is_not_recorded_as_completed(
    db_session: Session,
):
    """An adapter that reports success=False must not produce a completed payout."""
    provider = RecordingProviderAdapter()
    provider.success = False
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)
    key = "gw-provider-unsuccessful-0001"

    with pytest.raises(PaymentProviderException) as excinfo:
        service.execute_payout(
            db=db_session,
            request=make_request(NORMAL_SESSION_ID, idempotency_key=key),
            principal=make_principal(),
        )

    assert excinfo.value.code == "PROVIDER_EXECUTION_UNSUCCESSFUL"
    assert payouts_for_key(db_session, key) == []

    record = idempotency_record(db_session, key)
    assert record.status == "failed"


def test_provider_failure_does_not_leave_a_duplicate_payout_record(db_session: Session):
    """A failed attempt is not persisted as a payout at all."""
    provider = RecordingProviderAdapter()
    provider.error = PaymentProviderException(
        message="Network communication failure with PayPal Sandbox.",
        code="PAYPAL_NETWORK_FAILURE",
    )
    service = build_service(StubRiskEngine(TrustLevel.NORMAL, 5.0), provider=provider)
    key = "gw-provider-failure-0002"

    with pytest.raises(PaymentProviderException):
        service.execute_payout(
            db=db_session,
            request=make_request(NORMAL_SESSION_ID, idempotency_key=key),
            principal=make_principal(),
        )

    assert len(payouts_for_key(db_session, key)) == 0
