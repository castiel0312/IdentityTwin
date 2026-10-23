"""
Unit tests for the PayPal Sandbox provider adapter (app/gateway/provider.py).

Scope:
  * OAuth2 client-credentials token retrieval, caching and expiry handling,
  * missing / invalid credential handling,
  * transport failures (timeouts, network errors) and HTTP error mapping,
  * the Payouts API request payload contract,
  * PayPal-Request-Id provider level idempotency,
  * provider transaction identifiers and audit details,
  * webhook signature verification.

SAFETY: no test in this module may contact PayPal (sandbox or production).
Every HTTP interaction is served by httpx.MockTransport against a reserved
".test" host, and an autouse guard fails the test if any code path tries to
open a real socket. The ambient PayPal settings (which may hold real sandbox
credentials) are blanked for the duration of the module.
"""

import base64
import json
import time
import uuid
from urllib.parse import parse_qsl

import httpx
import pytest

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationRequiredException,
    PaymentProviderException,
    ProviderRateLimitException,
    ProviderTimeoutException,
)
from app.gateway.provider import (
    PAYPAL_REQUEST_ID_MAX_LENGTH,
    PayPalSandboxAdapter,
    build_paypal_request_id,
)
from app.schemas.payouts import PayoutRequest

FAKE_BASE_URL = "https://paypal-sandbox.test"
TOKEN_PATH = "/v1/oauth2/token"
PAYOUTS_PATH = "/v1/payments/payouts"
VERIFY_PATH = "/v1/notifications/verify-webhook-signature"

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
WEBHOOK_ID = "test-webhook-id"

MERCHANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class RecordedRequest:
    """Immutable snapshot of an outbound HTTP request."""

    def __init__(self, request: httpx.Request):
        self.method = request.method
        self.url = str(request.url)
        self.path = request.url.path
        self.headers = {key.lower(): value for key, value in request.headers.items()}
        self.body = request.content

    def json(self) -> dict:
        return json.loads(self.body)

    def form(self) -> dict[str, str]:
        return dict(parse_qsl(self.body.decode("utf-8")))

    def basic_auth_credentials(self) -> str:
        scheme, _, token = self.headers["authorization"].partition(" ")
        assert scheme.lower() == "basic"
        return base64.b64decode(token).decode("utf-8")


class MockPayPalServer:
    """
    Deterministic PayPal Sandbox stand-in backed by httpx.MockTransport.

    Responses are queued explicitly: an unexpected request raises immediately
    instead of silently returning a default, so every test states exactly
    which PayPal calls it expects.
    """

    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []
        self._queue: list[tuple[httpx.Response | None, Exception | None]] = []

    def queue_response(
        self,
        status_code: int,
        json_body: dict | None = None,
        *,
        text: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> "MockPayPalServer":
        if text is not None:
            response = httpx.Response(status_code, text=text, headers=headers or {})
        else:
            response = httpx.Response(
                status_code, json=json_body if json_body is not None else {}, headers=headers or {}
            )
        self._queue.append((response, None))
        return self

    def queue_error(self, error: Exception) -> "MockPayPalServer":
        self._queue.append((None, error))
        return self

    def queue_token(
        self, access_token: str = "ACCESS-TOKEN-1", expires_in: int = 3600
    ) -> "MockPayPalServer":
        return self.queue_response(
            200,
            {
                "access_token": access_token,
                "expires_in": expires_in,
                "token_type": "Bearer",
                "scope": "https://uri.paypal.com/services/payments/payouts",
            },
        )

    def queue_payout(
        self,
        payout_batch_id: str = "PAYOUT-BATCH-1",
        batch_status: str = "PENDING",
        status_code: int = 201,
    ) -> "MockPayPalServer":
        return self.queue_response(
            status_code,
            {
                "batch_header": {
                    "payout_batch_id": payout_batch_id,
                    "batch_status": batch_status,
                    "time_created": "2026-01-01T00:00:00Z",
                    "time_completed": "2026-01-01T00:00:05Z",
                },
                "links": [],
            },
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(RecordedRequest(request))
        if not self._queue:
            raise AssertionError(f"Unexpected PayPal request: {request.method} {request.url}")
        response, error = self._queue.pop(0)
        if error is not None:
            raise error
        return response

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def requests_to(self, path: str) -> list[RecordedRequest]:
        return [req for req in self.requests if req.path == path]


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    """Guard rail: no test may open a real socket."""

    def _blocked(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            f"Real network access is forbidden in tests: {request.method} {request.url}"
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)


@pytest.fixture(autouse=True)
def isolate_ambient_paypal_settings(monkeypatch):
    """
    The repository .env may hold real PayPal sandbox credentials.

    They are blanked for this module so that no test can authenticate against
    (or reach) the real PayPal API, even by accident.
    """
    monkeypatch.setattr(settings, "PAYPAL_CLIENT_ID", "")
    monkeypatch.setattr(settings, "PAYPAL_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "PAYPAL_WEBHOOK_ID", "")
    monkeypatch.setattr(settings, "PAYPAL_BASE_URL", FAKE_BASE_URL)


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
        webhook_id=WEBHOOK_ID,
        transport=paypal.transport,
    )


def make_payout_request(**overrides) -> PayoutRequest:
    payload = {
        "session_id": str(uuid.uuid4()),
        "recipient_email": "contractor@supplier.com",
        "amount": 1250.50,
        "currency": "USD",
        "reference_note": "Invoice #4021",
        "idempotency_key": "idem-key-00000001",
    }
    payload.update(overrides)
    return PayoutRequest(**payload)


def webhook_headers(**overrides) -> dict[str, str]:
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.paypal.com/certs/example",
        "paypal-transmission-id": "transmission-123",
        "paypal-transmission-sig": "signature-abc",
        "paypal-transmission-time": "2026-01-01T00:00:00Z",
    }
    headers.update(overrides)
    return headers


# ----------------------------------------------------------------------
# OAuth2 access token retrieval
# ----------------------------------------------------------------------


def test_oauth_token_request_uses_the_client_credentials_grant(adapter, paypal):
    """The token call is a form encoded client_credentials grant over Basic auth."""
    paypal.queue_token(access_token="TOKEN-ABC")

    assert adapter._get_access_token() == "TOKEN-ABC"

    assert len(paypal.requests) == 1
    request = paypal.requests[0]
    assert request.method == "POST"
    assert request.url == f"{FAKE_BASE_URL}{TOKEN_PATH}"
    assert request.path == TOKEN_PATH
    assert request.basic_auth_credentials() == f"{CLIENT_ID}:{CLIENT_SECRET}"
    assert request.form() == {"grant_type": "client_credentials"}
    assert request.headers["accept"] == "application/json"
    assert request.headers["accept-language"] == "en_US"


def test_valid_access_token_is_cached_and_not_refetched(adapter, paypal):
    """A token that is still comfortably valid is served from the cache."""
    paypal.queue_token(access_token="TOKEN-1", expires_in=3600)

    assert adapter._get_access_token() == "TOKEN-1"
    assert adapter._get_access_token() == "TOKEN-1"
    assert adapter._get_access_token() == "TOKEN-1"

    assert len(paypal.requests_to(TOKEN_PATH)) == 1


def test_token_is_refreshed_when_it_enters_the_expiry_skew(adapter, paypal):
    """A token with less than 60 seconds of life left is never reused."""
    paypal.queue_token(access_token="TOKEN-OLD", expires_in=3600)
    assert adapter._get_access_token() == "TOKEN-OLD"

    # The cached token expires in 30 seconds: inside the 60 second skew.
    adapter._token_cache = ("TOKEN-OLD", time.time() + 30)
    paypal.queue_token(access_token="TOKEN-NEW", expires_in=3600)

    assert adapter._get_access_token() == "TOKEN-NEW"
    assert len(paypal.requests_to(TOKEN_PATH)) == 2


def test_expired_token_is_refetched(adapter, paypal):
    """An already expired token is never served from the cache."""
    paypal.queue_token(access_token="TOKEN-OLD", expires_in=0)
    assert adapter._get_access_token() == "TOKEN-OLD"

    paypal.queue_token(access_token="TOKEN-NEW", expires_in=3600)

    assert adapter._get_access_token() == "TOKEN-NEW"
    assert len(paypal.requests_to(TOKEN_PATH)) == 2


def test_missing_credentials_raise_authentication_required_without_http_traffic(paypal):
    """Without credentials the adapter fails closed before any HTTP call."""
    adapter = PayPalSandboxAdapter(
        client_id="",
        client_secret="",
        base_url=FAKE_BASE_URL,
        transport=paypal.transport,
    )

    with pytest.raises(AuthenticationRequiredException) as excinfo:
        adapter._get_access_token()

    assert excinfo.value.code == "PAYPAL_CREDENTIALS_MISSING"
    assert excinfo.value.status_code == 401
    assert paypal.requests == []


def test_missing_client_secret_alone_is_rejected(paypal):
    """A client id without a secret is not a usable credential pair."""
    adapter = PayPalSandboxAdapter(
        client_id=CLIENT_ID,
        client_secret="",
        base_url=FAKE_BASE_URL,
        transport=paypal.transport,
    )

    with pytest.raises(AuthenticationRequiredException) as excinfo:
        adapter._get_access_token()

    assert excinfo.value.code == "PAYPAL_CREDENTIALS_MISSING"
    assert paypal.requests == []


@pytest.mark.parametrize("status_code", [401, 403])
def test_oauth_credential_rejection_maps_to_authentication_required(adapter, paypal, status_code):
    """Rejected sandbox credentials surface as an authentication failure."""
    paypal.queue_response(status_code, {"error": "invalid_client"})

    with pytest.raises(AuthenticationRequiredException) as excinfo:
        adapter._get_access_token()

    assert excinfo.value.code == "PAYPAL_AUTHENTICATION_FAILED"
    assert excinfo.value.status_code == 401


def test_oauth_rate_limit_maps_to_provider_rate_limit(adapter, paypal):
    """A throttled token endpoint is reported as a rate limit, not a generic error."""
    paypal.queue_response(429, {"error": "too_many_requests"})

    with pytest.raises(ProviderRateLimitException) as excinfo:
        adapter._get_access_token()

    assert excinfo.value.code == "PAYPAL_RATE_LIMIT"
    assert excinfo.value.status_code == 429


@pytest.mark.parametrize("status_code", [500, 502, 503])
def test_oauth_server_error_maps_to_payment_provider_exception(adapter, paypal, status_code):
    """Unexpected token endpoint statuses are provider errors."""
    paypal.queue_response(status_code, {"error": "server_error"})

    with pytest.raises(PaymentProviderException) as excinfo:
        adapter._get_access_token()

    assert excinfo.value.code == "PAYPAL_OAUTH_ERROR"
    assert excinfo.value.status_code == 502


def test_oauth_response_without_access_token_is_an_invalid_payload(adapter, paypal):
    """A successful HTTP status without a token is a contract violation."""
    paypal.queue_response(200, {"token_type": "Bearer"})

    with pytest.raises(PaymentProviderException) as excinfo:
        adapter._get_access_token()

    assert excinfo.value.code == "PAYPAL_OAUTH_INVALID_PAYLOAD"


def test_oauth_non_json_body_is_an_invalid_payload(adapter, paypal):
    """A non-JSON token body must not surface as an unhandled decoding error."""
    paypal.queue_response(200, text="<html>gateway error</html>")

    with pytest.raises(PaymentProviderException) as excinfo:
        adapter._get_access_token()

    assert excinfo.value.code == "PAYPAL_OAUTH_INVALID_PAYLOAD"


def test_oauth_timeout_maps_to_provider_timeout(adapter, paypal):
    """A slow token endpoint is reported as a timeout, not as a generic error."""
    paypal.queue_error(httpx.ReadTimeout("token request timed out"))

    with pytest.raises(ProviderTimeoutException) as excinfo:
        adapter._get_access_token()

    assert excinfo.value.code == "PAYPAL_OAUTH_TIMEOUT"
    assert excinfo.value.status_code == 504


def test_oauth_network_error_maps_to_payment_provider_exception(adapter, paypal):
    """Connection level failures are reported without leaking internals."""
    paypal.queue_error(httpx.ConnectError("connection refused"))

    with pytest.raises(PaymentProviderException) as excinfo:
        adapter._get_access_token()

    assert excinfo.value.code == "PAYPAL_NETWORK_ERROR"
    assert "ConnectError" in excinfo.value.message


# ----------------------------------------------------------------------
# Payout execution
# ----------------------------------------------------------------------


def test_payout_is_posted_to_the_paypal_payouts_endpoint(adapter, paypal):
    """The payout call targets /v1/payments/payouts with a bearer token."""
    paypal.queue_token()
    paypal.queue_payout()

    adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    payouts = paypal.requests_to(PAYOUTS_PATH)
    assert len(payouts) == 1
    assert payouts[0].method == "POST"
    assert payouts[0].url == f"{FAKE_BASE_URL}{PAYOUTS_PATH}"
    assert payouts[0].headers["authorization"] == "Bearer ACCESS-TOKEN-1"
    assert payouts[0].headers["content-type"] == "application/json"


def test_payout_payload_matches_the_paypal_payouts_contract(adapter, paypal):
    """The request body follows the PayPal Payouts API contract."""
    paypal.queue_token()
    paypal.queue_payout()

    adapter.execute_payout(make_payout_request(amount=1250.5), MERCHANT_ID)

    body = paypal.requests_to(PAYOUTS_PATH)[0].json()

    header = body["sender_batch_header"]
    assert header["sender_batch_id"].startswith("IDTWIN-")
    assert header["email_subject"] == "IdentityTwin Protected Disbursement"
    assert header["email_message"] == "Invoice #4021"

    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["recipient_type"] == "EMAIL"
    assert item["amount"] == {"value": "1250.50", "currency": "USD"}
    assert item["note"] == "Invoice #4021"
    assert item["sender_item_id"].startswith("ITEM-")
    assert item["receiver"] == "contractor@supplier.com"


def test_payout_payload_uses_default_wording_without_a_reference_note(adapter, paypal):
    """A payout without a reference note still carries a meaningful note."""
    paypal.queue_token()
    paypal.queue_payout()

    request = make_payout_request(reference_note=None)
    adapter.execute_payout(request, MERCHANT_ID)

    body = paypal.requests_to(PAYOUTS_PATH)[0].json()
    assert body["sender_batch_header"]["email_message"]
    assert body["items"][0]["note"] == "Protected payout"


def test_payout_amount_is_formatted_with_two_decimals(adapter, paypal):
    """Amounts are sent as PayPal decimal strings, never as raw floats."""
    paypal.queue_token()
    paypal.queue_payout()

    adapter.execute_payout(make_payout_request(amount=10), MERCHANT_ID)

    body = paypal.requests_to(PAYOUTS_PATH)[0].json()
    assert body["items"][0]["amount"]["value"] == "10.00"


def test_payout_never_sends_the_client_secret(adapter, paypal):
    """Only the bearer token is transmitted; the client secret stays server side."""
    paypal.queue_token()
    paypal.queue_payout()

    adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    for request in paypal.requests:
        assert CLIENT_SECRET not in request.body.decode("utf-8", errors="ignore")
        assert CLIENT_SECRET not in str(request.headers)


def test_paypal_request_id_header_carries_the_idempotency_key(adapter, paypal):
    """The gateway idempotency key is forwarded as the PayPal request id."""
    paypal.queue_token()
    paypal.queue_payout()

    adapter.execute_payout(make_payout_request(idempotency_key="idem-key-00000042"), MERCHANT_ID)

    request = paypal.requests_to(PAYOUTS_PATH)[0]
    assert request.headers["paypal-request-id"] == "idem-key-00000042"


def test_overlong_idempotency_key_is_mapped_to_a_stable_bounded_request_id(adapter, paypal):
    """
    PayPal rejects request ids longer than 38 characters.

    Over-long gateway keys are mapped to a deterministic digest so that
    provider level idempotency is preserved and the call is still accepted.
    """
    long_key = "k" * 128
    paypal.queue_token()
    paypal.queue_payout()

    adapter.execute_payout(make_payout_request(idempotency_key=long_key), MERCHANT_ID)

    request_id = paypal.requests_to(PAYOUTS_PATH)[0].headers["paypal-request-id"]
    assert len(request_id) <= PAYPAL_REQUEST_ID_MAX_LENGTH
    assert request_id != long_key
    # Deterministic: the same key always maps to the same provider request id.
    assert request_id == build_paypal_request_id(long_key)
    assert build_paypal_request_id(long_key) == build_paypal_request_id(long_key)


def test_build_paypal_request_id_keeps_short_keys_verbatim():
    """Keys that already fit PayPal's limit are forwarded unchanged."""
    assert build_paypal_request_id("short-key") == "short-key"
    assert len(build_paypal_request_id("x" * PAYPAL_REQUEST_ID_MAX_LENGTH)) == (
        PAYPAL_REQUEST_ID_MAX_LENGTH
    )


def test_payout_transaction_id_comes_from_the_paypal_batch_header(adapter, paypal):
    """The provider transaction id is the PayPal payout batch id."""
    paypal.queue_token()
    paypal.queue_payout(payout_batch_id="8XY12345ABC", batch_status="PENDING")

    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    assert result.provider_transaction_id == "8XY12345ABC"
    assert result.success is True
    assert result.provider_name == "paypal_sandbox"
    assert result.environment == "paypal_sandbox"
    assert result.executed_at.tzinfo is not None


def test_payout_transaction_id_falls_back_to_the_generated_batch_id(adapter, paypal):
    """A response without a batch id still yields a traceable transaction id."""
    paypal.queue_token()
    paypal.queue_response(201, {"batch_header": {"batch_status": "PENDING"}})

    result = adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    assert result.provider_transaction_id.startswith("IDTWIN-")


def test_payout_result_details_capture_the_batch_provenance(adapter, paypal):
    """The audit details carry the batch identifiers and the payout context."""
    paypal.queue_token()
    paypal.queue_payout(payout_batch_id="BATCH-9", batch_status="SUCCESS")

    request = make_payout_request()
    result = adapter.execute_payout(request, MERCHANT_ID)

    assert result.details["batch_status"] == "SUCCESS"
    assert result.details["sender_batch_id"].startswith("IDTWIN-")
    assert result.details["time_created"] == "2026-01-01T00:00:00Z"
    assert result.details["time_completed"] == "2026-01-01T00:00:05Z"
    assert result.details["recipient"] == request.recipient_email
    assert result.details["amount"] == request.amount
    assert result.details["currency"] == request.currency
    assert result.details["merchant_id"] == str(MERCHANT_ID)


def test_successive_payouts_reuse_the_cached_token(adapter, paypal):
    """The token is fetched once and reused for subsequent payouts."""
    paypal.queue_token()
    paypal.queue_payout(payout_batch_id="BATCH-1")
    paypal.queue_payout(payout_batch_id="BATCH-2")

    adapter.execute_payout(make_payout_request(idempotency_key="idem-key-00000001"), MERCHANT_ID)
    adapter.execute_payout(make_payout_request(idempotency_key="idem-key-00000002"), MERCHANT_ID)

    assert len(paypal.requests_to(TOKEN_PATH)) == 1
    assert len(paypal.requests_to(PAYOUTS_PATH)) == 2


def test_payout_rate_limit_maps_to_provider_rate_limit(adapter, paypal):
    """PayPal throttling during execution is reported as a rate limit."""
    paypal.queue_token()
    paypal.queue_response(429, {"name": "TOO_MANY_REQUESTS"})

    with pytest.raises(ProviderRateLimitException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    assert excinfo.value.code == "PAYPAL_RATE_LIMIT"
    assert excinfo.value.status_code == 429


def test_payout_unauthorized_invalidates_the_cached_token(adapter, paypal):
    """A rejected token is dropped from the cache so the next call re-authenticates."""
    paypal.queue_token()
    paypal.queue_response(401, {"name": "AUTHENTICATION_FAILURE"})

    with pytest.raises(AuthenticationRequiredException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    assert excinfo.value.code == "PAYPAL_TOKEN_INVALID"
    assert adapter._token_cache is None


def test_payout_rejection_maps_to_payment_provider_exception(adapter, paypal):
    """A business rejection is reported with PayPal's own error name and message."""
    paypal.queue_token()
    paypal.queue_response(
        400,
        {
            "name": "INVALID_REQUEST",
            "message": "Recipient email is invalid.",
            "details": [{"issue": "INVALID_EMAIL"}],
        },
    )

    with pytest.raises(PaymentProviderException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    assert excinfo.value.code == "PAYPAL_PAYOUT_REJECTED"
    assert "INVALID_REQUEST" in excinfo.value.message
    assert "Recipient email is invalid." in excinfo.value.message
    assert excinfo.value.details["paypal_error_name"] == "INVALID_REQUEST"
    assert excinfo.value.details["details"] == [{"issue": "INVALID_EMAIL"}]


def test_payout_unprocessable_entity_maps_to_payment_provider_exception(adapter, paypal):
    """HTTP 422 is handled like any other business rejection."""
    paypal.queue_token()
    paypal.queue_response(422, {"name": "UNPROCESSABLE_ENTITY", "message": "Amount too large."})

    with pytest.raises(PaymentProviderException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    assert excinfo.value.code == "PAYPAL_PAYOUT_REJECTED"
    assert excinfo.value.details["paypal_error_name"] == "UNPROCESSABLE_ENTITY"


def test_payout_rejection_with_a_non_json_body_is_still_mapped(adapter, paypal):
    """A non-JSON rejection body must not raise an unhandled decoding error."""
    paypal.queue_token()
    paypal.queue_response(400, text="<html>bad request</html>")

    with pytest.raises(PaymentProviderException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    assert excinfo.value.code == "PAYPAL_PAYOUT_REJECTED"
    assert excinfo.value.details["paypal_error_name"] == "UNPROCESSABLE_ENTITY"


@pytest.mark.parametrize("status_code", [500, 502, 503, 404])
def test_payout_unexpected_status_maps_to_payment_provider_exception(adapter, paypal, status_code):
    """Unexpected provider statuses are surfaced with the original status code."""
    paypal.queue_token()
    paypal.queue_response(status_code, {"name": "INTERNAL_SERVER_ERROR"})

    with pytest.raises(PaymentProviderException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    assert excinfo.value.code == "PAYPAL_UNEXPECTED_RESPONSE"
    assert excinfo.value.details["status_code"] == status_code


def test_payout_timeout_maps_to_provider_timeout_with_the_idempotency_key(adapter, paypal):
    """
    A payout timeout is ambiguous: the outcome may already be committed
    upstream, so the idempotency key is reported for reconciliation.
    """
    paypal.queue_token()
    paypal.queue_error(httpx.ReadTimeout("payout request timed out"))

    with pytest.raises(ProviderTimeoutException) as excinfo:
        adapter.execute_payout(make_payout_request(idempotency_key="idem-key-timeout"), MERCHANT_ID)

    assert excinfo.value.code == "PAYPAL_PAYOUT_TIMEOUT"
    assert excinfo.value.status_code == 504
    assert excinfo.value.details["idempotency_key"] == "idem-key-timeout"


def test_payout_network_error_maps_to_payment_provider_exception(adapter, paypal):
    """Connection level failures during execution are provider errors."""
    paypal.queue_token()
    paypal.queue_error(httpx.ConnectError("connection reset"))

    with pytest.raises(PaymentProviderException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    assert excinfo.value.code == "PAYPAL_NETWORK_FAILURE"
    assert "ConnectError" in excinfo.value.message


def test_payout_non_json_success_body_maps_to_payment_provider_exception(adapter, paypal):
    """A successful status with an undecodable body is a provider contract error."""
    paypal.queue_token()
    paypal.queue_response(201, text="not json at all")

    with pytest.raises(PaymentProviderException) as excinfo:
        adapter.execute_payout(make_payout_request(), MERCHANT_ID)

    assert excinfo.value.code == "PAYPAL_INVALID_RESPONSE"


# ----------------------------------------------------------------------
# Webhook signature verification
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_header",
    [
        "paypal-auth-algo",
        "paypal-cert-url",
        "paypal-transmission-id",
        "paypal-transmission-sig",
        "paypal-transmission-time",
    ],
)
def test_webhook_verification_requires_the_full_paypal_header_set(adapter, paypal, missing_header):
    """An incomplete header set is rejected without contacting PayPal."""
    headers = webhook_headers()
    headers.pop(missing_header)

    assert adapter.verify_webhook_signature(headers=headers, raw_body=b"{}") is False
    assert paypal.requests == []


def test_webhook_verification_returns_true_for_a_successful_verification(adapter, paypal):
    """PayPal's own verification decision is honoured."""
    paypal.queue_token()
    paypal.queue_response(200, {"verification_status": "SUCCESS"})

    verified = adapter.verify_webhook_signature(
        headers=webhook_headers(), raw_body=b'{"event_type":"PAYMENT.PAYOUTSBATCH.SUCCESS"}'
    )

    assert verified is True
    assert len(paypal.requests_to(VERIFY_PATH)) == 1


def test_webhook_verification_returns_false_for_a_failed_verification(adapter, paypal):
    """PayPal rejecting the signature is a failed verification."""
    paypal.queue_token()
    paypal.queue_response(200, {"verification_status": "FAILURE"})

    verified = adapter.verify_webhook_signature(headers=webhook_headers(), raw_body=b"{}")

    assert verified is False


def test_webhook_verification_returns_false_on_a_non_200_response(adapter, paypal):
    """A provider error never yields a verified webhook."""
    paypal.queue_token()
    paypal.queue_response(500, {"name": "INTERNAL_SERVER_ERROR"})

    verified = adapter.verify_webhook_signature(headers=webhook_headers(), raw_body=b"{}")

    assert verified is False


def test_webhook_verification_sends_the_expected_payload(adapter, paypal):
    """The verification request carries every PayPal header value and the event."""
    paypal.queue_token()
    paypal.queue_response(200, {"verification_status": "SUCCESS"})

    adapter.verify_webhook_signature(
        headers=webhook_headers(), raw_body=b'{"id":"EVENT-1","event_type":"PAYMENT.PAYOUTS"}'
    )

    body = paypal.requests_to(VERIFY_PATH)[0].json()
    assert body["auth_algo"] == "SHA256withRSA"
    assert body["cert_url"] == "https://api.paypal.com/certs/example"
    assert body["transmission_id"] == "transmission-123"
    assert body["transmission_sig"] == "signature-abc"
    assert body["transmission_time"] == "2026-01-01T00:00:00Z"
    assert body["webhook_id"] == WEBHOOK_ID
    assert body["webhook_event"] == {"id": "EVENT-1", "event_type": "PAYMENT.PAYOUTS"}


def test_webhook_verification_fails_closed_when_paypal_is_unreachable(adapter, paypal):
    """A provider outage must never be treated as a verified webhook."""
    paypal.queue_token()
    paypal.queue_error(httpx.ConnectError("connection refused"))

    verified = adapter.verify_webhook_signature(headers=webhook_headers(), raw_body=b"{}")

    assert verified is False


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_webhook_verification_is_rejected_without_configuration_in_any_environment(
    paypal, monkeypatch, environment
):
    """
    Without configured credentials the webhook is rejected in every environment.

    There is no environment in which an unconfigured adapter accepts a
    signature: the removed development fallback only checked whether the
    signature "looked plausible".
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    adapter = PayPalSandboxAdapter(
        client_id="",
        client_secret="",
        webhook_id="",
        base_url=FAKE_BASE_URL,
        transport=paypal.transport,
    )

    verified = adapter.verify_webhook_signature(headers=webhook_headers(), raw_body=b"{}")

    assert verified is False
    assert paypal.requests == []


def test_webhook_verification_rejects_a_plausible_signature_without_configuration(paypal):
    """
    A signature that merely looks plausible is rejected when no verification
    is possible, even in the development environment.
    """
    adapter = PayPalSandboxAdapter(
        client_id="",
        client_secret="",
        webhook_id="",
        base_url=FAKE_BASE_URL,
        transport=paypal.transport,
    )

    headers = webhook_headers(**{"paypal-transmission-sig": "PLAUSIBLE-LOOKING-SIGNATURE"})

    assert adapter.verify_webhook_signature(headers=headers, raw_body=b"{}") is False
    assert paypal.requests == []
