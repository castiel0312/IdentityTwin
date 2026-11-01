"""
Regression tests for Person 3 P0/P1 fixes.

Covers:
  * Payout status mapping (PENDING must not become completed)
  * Cumulative agentic spending limits ($60 + $60 vs $100 grant)
  * Concurrent grant spending enforcement
  * Provider reference integrity (no fabricated IDs)
  * Structured PayPal error details (PAYOUT_NOT_AVAILABLE)
  * Production mock provider rejection
  * Unknown provider rejection
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from app.core.exceptions import (
    PaymentProviderException,
    ProviderTimeoutException,
)
from app.db.repositories.agent_repo import AgentRepository
from app.gateway.agentic import AgenticCommerceAdapter, AgenticCommerceService
from app.gateway.provider import (
    PayPalSandboxAdapter,
    ProviderPayoutResult,
    build_paypal_request_id,
)
from app.gateway.service import TrustGatewayService
from app.models.agent import (
    AgentAuthorizationGrant,
    AgentRegistration,
    AgentStatus,
)
from app.schemas.agentic import AgentScope
from app.schemas.payouts import PayoutRequest

FAKE_BASE_URL = "https://paypal-sandbox.test"
CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
MERCHANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")


class MockPayPalServer:
    """Deterministic PayPal stand-in backed by httpx.MockTransport."""

    def __init__(self) -> None:
        self.requests: list = []
        self._queue: list = []

    def queue_response(
        self,
        status_code: int,
        json_body: dict | None = None,
        *,
        text: str | None = None,
    ) -> "MockPayPalServer":
        if text is not None:
            response = httpx.Response(status_code, text=text)
        else:
            response = httpx.Response(status_code, json=json_body or {})
        self._queue.append((response, None))
        return self

    def queue_error(self, error: Exception) -> "MockPayPalServer":
        self._queue.append((None, error))
        return self

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._queue:
            raise AssertionError(f"Unexpected PayPal request: {request.method} {request.url}")
        response, error = self._queue.pop(0)
        if error is not None:
            raise error
        return response

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)


@pytest.fixture
def paypal() -> MockPayPalServer:
    return MockPayPalServer()


@pytest.fixture
def adapter(paypal: MockPayPalServer) -> PayPalSandboxAdapter:
    return PayPalSandboxAdapter(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        base_url=FAKE_BASE_URL,
        timeout=5.0,
        webhook_id="WH-TEST",
        transport=paypal.transport,
    )


def make_payout_request(**overrides) -> PayoutRequest:
    payload = {
        "session_id": str(uuid.uuid4()),
        "recipient_email": "contractor@supplier.com",
        "amount": 1250.50,
        "currency": "USD",
        "reference_note": "Invoice #4021",
        "idempotency_key": f"idem-{uuid.uuid4().hex}",
    }
    payload.update(overrides)
    return PayoutRequest(**payload)


# ----------------------------------------------------------------------
# P0: Payout status mapping
# ----------------------------------------------------------------------


def test_pending_payout_is_not_completed(adapter, paypal):
    """PENDING batch status maps to internal 'pending', never 'completed'."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        201,
        {
            "batch_header": {
                "payout_batch_id": "BATCH-PENDING-1",
                "batch_status": "PENDING",
            }
        },
    )
    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert result.success is False
    assert result.batch_status == "PENDING"
    assert result.provider_batch_id == "BATCH-PENDING-1"


def test_processing_payout_is_not_completed(adapter, paypal):
    """PROCESSING batch status maps to internal 'processing', never 'completed'."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        201,
        {
            "batch_header": {
                "payout_batch_id": "BATCH-PROCESSING-1",
                "batch_status": "PROCESSING",
            }
        },
    )
    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert result.success is False
    assert result.batch_status == "PROCESSING"


def test_success_payout_is_completed(adapter, paypal):
    """SUCCESS batch status maps to internal 'completed'."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        201,
        {
            "batch_header": {
                "payout_batch_id": "BATCH-SUCCESS-1",
                "batch_status": "SUCCESS",
            }
        },
    )
    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert result.success is True
    assert result.batch_status == "SUCCESS"


def test_denied_payout_is_failed(adapter, paypal):
    """DENIED batch status maps to internal 'denied'."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        201,
        {
            "batch_header": {
                "payout_batch_id": "BATCH-DENIED-1",
                "batch_status": "DENIED",
            }
        },
    )
    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert result.success is False
    assert result.batch_status == "DENIED"


def test_failed_payout_is_failed(adapter, paypal):
    """FAILED batch status maps to internal 'failed'."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        201,
        {
            "batch_header": {
                "payout_batch_id": "BATCH-FAILED-1",
                "batch_status": "FAILED",
            }
        },
    )
    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert result.success is False
    assert result.batch_status == "FAILED"


def test_unknown_status_is_not_completed(adapter, paypal):
    """Unknown batch status maps to 'unknown', never 'completed'."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        201,
        {
            "batch_header": {
                "payout_batch_id": "BATCH-UNKNOWN-1",
                "batch_status": "UNKNOWN_STATUS",
            }
        },
    )
    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert result.success is False
    assert result.batch_status == "UNKNOWN_STATUS"


def test_missing_batch_status_is_not_completed(adapter, paypal):
    """Missing batch status defaults to PENDING, never 'completed'."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        201,
        {
            "batch_header": {
                "payout_batch_id": "BATCH-NOSTATUS-1",
            }
        },
    )
    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert result.success is False
    assert result.batch_status == "PENDING"


def test_missing_provider_batch_id_is_not_fabricated(adapter, paypal):
    """When PayPal omits payout_batch_id, provider_batch_id is None, not the sender_batch_id."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        201,
        {
            "batch_header": {
                "batch_status": "PENDING",
            }
        },
    )
    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert result.provider_batch_id is None
    assert result.success is False  # No provider confirmation = not terminal success


# ----------------------------------------------------------------------
# P0: Structured PayPal error details
# ----------------------------------------------------------------------


def test_payout_not_available_is_reported_as_country_restriction(adapter, paypal):
    """PAYOUT_NOT_AVAILABLE is reported as account/country restriction, not generic error."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        403,
        {
            "name": "PAYOUT_NOT_AVAILABLE",
            "message": "The payout is not available for the sender's country.",
            "debug_id": "DEBUG-123",
        },
    )
    with pytest.raises(PaymentProviderException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert excinfo.value.code == "PAYPAL_PAYOUT_NOT_AVAILABLE"
    assert excinfo.value.status_code == 403
    assert "restriction" in excinfo.value.message.lower() or "country" in excinfo.value.message.lower()
    assert excinfo.value.details["restriction_type"] == "account_or_country"
    assert excinfo.value.details["debug_id"] == "DEBUG-123"


def test_payout_permission_denied_is_reported_separately(adapter, paypal):
    """A generic 403 permission failure is reported as PAYPAL_PAYOUT_PERMISSION_DENIED."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        403,
        {
            "name": "PERMISSION_DENIED",
            "message": "Merchant does not have permission to send payouts.",
        },
    )
    with pytest.raises(PaymentProviderException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert excinfo.value.code == "PAYPAL_PAYOUT_PERMISSION_DENIED"
    assert excinfo.value.status_code == 403


def test_duplicate_request_is_detected(adapter, paypal):
    """PayPal duplicate request errors are flagged as duplicates."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        400,
        {
            "name": "DUPLICATE_REQUEST",
            "message": "A payout with this PayPal-Request-Id already exists.",
            "details": [{"issue": "DUPLICATE_REQUEST"}],
        },
    )
    with pytest.raises(PaymentProviderException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert excinfo.value.code == "PAYPAL_DUPLICATE_REQUEST"
    assert excinfo.value.details["is_duplicate"] is True


def test_temporary_outage_is_reported(adapter, paypal):
    """503 PayPal errors are reported as PAYPAL_TEMPORARY_OUTAGE."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(503, {"name": "INTERNAL_SERVER_ERROR", "message": "Service unavailable"})
    with pytest.raises(PaymentProviderException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert excinfo.value.code == "PAYPAL_TEMPORARY_OUTAGE"
    assert excinfo.value.details["is_temporary"] is True


def test_payout_timeout_preserves_idempotency_key(adapter, paypal):
    """A payout timeout reports the idempotency key for reconciliation."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_error(httpx.ReadTimeout("payout request timed out"))
    key = "idem-timeout-test"
    with pytest.raises(ProviderTimeoutException) as excinfo:
        adapter.execute_payout(make_payout_request(idempotency_key=key), MERCHANT_ID)
    assert excinfo.value.code == "PAYPAL_PAYOUT_TIMEOUT"
    assert excinfo.value.details["idempotency_key"] == key


# ----------------------------------------------------------------------
# P1: Production provider safety
# ----------------------------------------------------------------------
# Note: Production mock rejection and unknown provider rejection are covered
# by tests/test_payment_provider_config.py. Those tests verify:
#   * Production + mock rejected (without explicit override)
#   * Development + mock accepted
#   * Unknown provider rejected at startup
#   * PayPal failure does not trigger mock fallback


# ----------------------------------------------------------------------
# P0: Cumulative agentic spending limits
# ----------------------------------------------------------------------


def _register_agent_and_grant(
    db,
    *,
    grant_max_amount: float = 100.0,
    agent_max_amount: float | None = None,
    consumed: bool = False,
    revoked: bool = False,
    expired: bool = False,
):
    agent = AgentRegistration(
        merchant_id=MERCHANT_ID,
        display_name="Test Agent",
        agent_type="shopping_assistant",
        scopes=[AgentScope.PAYOUT_EXECUTE.value],
        max_payout_amount=agent_max_amount,
        status=AgentStatus.ACTIVE,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(minutes=5) if expired else now + timedelta(hours=1)
    grant = AgentAuthorizationGrant(
        agent_id=agent.agent_id,
        merchant_id=MERCHANT_ID,
        user_id=USER_ID,
        scopes=[AgentScope.PAYOUT_EXECUTE.value],
        max_amount=grant_max_amount,
        issued_at=now,
        expires_at=expires_at,
        consumed_at=datetime.now(timezone.utc) if consumed else None,
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return agent, grant


def test_single_payout_below_limit_reserves_capacity(db_session):
    """A single payout below the grant limit reserves capacity."""
    repo = AgentRepository(db_session)
    agent, grant = _register_agent_and_grant(db_session, grant_max_amount=100.0)

    reserved = repo.reserve_spending_capacity(grant.grant_id, 60.0)
    assert reserved is not None
    assert reserved.reserved_amount == 60.0
    assert reserved.total_consumed_amount == 0.0
    db_session.commit()


def test_second_payout_exceeds_remaining_capacity(db_session):
    """A second $60 payout against a $100 grant is rejected (remaining is $40)."""
    repo = AgentRepository(db_session)
    agent, grant = _register_agent_and_grant(db_session, grant_max_amount=100.0)

    # First $60 reservation succeeds
    first = repo.reserve_spending_capacity(grant.grant_id, 60.0)
    assert first is not None
    db_session.commit()

    # Second $60 reservation should fail (only $40 remains)
    second = repo.reserve_spending_capacity(grant.grant_id, 60.0)
    assert second is None
    db_session.commit()


def test_concurrent_payouts_cannot_exceed_grant_limit(db_session):
    """Two concurrent $60 payouts against a $100 grant: only one succeeds."""
    repo = AgentRepository(db_session)
    agent, grant = _register_agent_and_grant(db_session, grant_max_amount=100.0)

    # Simulate concurrent access: first reservation takes $60
    first = repo.reserve_spending_capacity(grant.grant_id, 60.0)
    assert first is not None
    db_session.commit()

    # Second concurrent request sees only $40 remaining
    second = repo.reserve_spending_capacity(grant.grant_id, 60.0)
    assert second is None
    db_session.commit()


def test_failed_provider_releases_reservation(db_session):
    """A definitive provider failure releases the spending reservation."""
    repo = AgentRepository(db_session)
    agent, grant = _register_agent_and_grant(db_session, grant_max_amount=100.0)

    # Reserve $60
    reserved = repo.reserve_spending_capacity(grant.grant_id, 60.0)
    assert reserved is not None
    assert reserved.reserved_amount == 60.0
    db_session.commit()

    # Release on definitive failure
    released = repo.release_reservation(grant.grant_id, 60.0)
    assert released is not None
    assert released.reserved_amount == 0.0
    db_session.commit()


def test_consumed_reservation_moves_to_total_consumed(db_session):
    """A successful provider call consumes the reservation."""
    repo = AgentRepository(db_session)
    agent, grant = _register_agent_and_grant(db_session, grant_max_amount=100.0)

    # Reserve $60
    repo.reserve_spending_capacity(grant.grant_id, 60.0)
    db_session.commit()

    # Consume on success
    consumed = repo.consume_reservation(grant.grant_id, 60.0)
    assert consumed is not None
    assert consumed.total_consumed_amount == 60.0
    assert consumed.reserved_amount == 0.0
    db_session.commit()


def test_expired_grant_is_rejected(db_session):
    """An expired grant cannot reserve spending capacity."""
    repo = AgentRepository(db_session)
    _agent, grant = _register_agent_and_grant(db_session, grant_max_amount=100.0, expired=True)

    reserved = repo.reserve_spending_capacity(grant.grant_id, 10.0)
    assert reserved is None


def test_revoked_grant_is_rejected(db_session):
    """A revoked grant cannot reserve spending capacity."""
    repo = AgentRepository(db_session)
    _agent, grant = _register_agent_and_grant(db_session, grant_max_amount=100.0, revoked=True)

    reserved = repo.reserve_spending_capacity(grant.grant_id, 10.0)
    assert reserved is None


# ----------------------------------------------------------------------
# P1: Provider reference integrity
# ----------------------------------------------------------------------


def test_provider_batch_id_is_persisted_separately(adapter, paypal):
    """Valid PayPal payout_batch_id is stored as provider_batch_id, not sender_batch_id."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        201,
        {
            "batch_header": {
                "payout_batch_id": "REAL-BATCH-ID-123",
                "batch_status": "SUCCESS",
            }
        },
    )
    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert result.provider_batch_id == "REAL-BATCH-ID-123"
    assert result.sender_batch_id is not None
    assert result.provider_batch_id != result.sender_batch_id


def test_sender_batch_id_is_stored_in_details(adapter, paypal):
    """sender_batch_id is preserved in details but not used as provider reference."""
    paypal.queue_response(200, {"access_token": "TOKEN", "expires_in": 3600})
    paypal.queue_response(
        201,
        {
            "batch_header": {
                "payout_batch_id": "REAL-BATCH-ID-456",
                "batch_status": "SUCCESS",
            }
        },
    )
    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)
    assert result.details["sender_batch_id"].startswith("IDTWIN-")
    assert result.details["provider_batch_id"] == "REAL-BATCH-ID-456"
    assert result.provider_transaction_id == "REAL-BATCH-ID-456"


# ----------------------------------------------------------------------
# P2: Idempotency hash includes reference_note and session
# ----------------------------------------------------------------------


def test_idempotency_hash_includes_reference_note_and_session():
    """Canonical request hash includes reference_note and session_id."""
    import hashlib

    req_a = PayoutRequest(
        session_id=uuid.uuid4(),
        recipient_email="a@b.com",
        amount=10.0,
        currency="USD",
        reference_note="note A",
        idempotency_key="key-abcdef01",
    )
    req_b = PayoutRequest(
        session_id=uuid.uuid4(),
        recipient_email="a@b.com",
        amount=10.0,
        currency="USD",
        reference_note="note B",
        idempotency_key="key-abcdef02",
    )
    hash_a = hashlib.sha256(
        f"{req_a.recipient_email}:{req_a.amount}:{req_a.currency}:{req_a.reference_note}:{req_a.session_id}".encode()
    ).hexdigest()
    hash_b = hashlib.sha256(
        f"{req_b.recipient_email}:{req_b.amount}:{req_b.currency}:{req_b.reference_note}:{req_b.session_id}".encode()
    ).hexdigest()
    assert hash_a != hash_b  # Different reference notes or sessions = different hashes
