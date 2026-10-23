"""
Fail-closed webhook signature verification tests.

Security context
----------------
The PayPal webhook receiver used to have two insecure acceptance paths:

1. `PayPalSandboxAdapter.verify_webhook_signature` fell back to "accept any
   signature that looks plausible" whenever the PayPal webhook configuration
   was missing and the app ran in the development environment.
2. `MockPaymentProviderAdapter.verify_webhook_signature` accepted any
   signature that did not literally contain the word "invalid".

Either path allowed an unauthenticated caller to forge a payout
reconciliation event. Both are now fail-closed: a webhook is accepted only
when PayPal itself confirms the signature through
`/v1/notifications/verify-webhook-signature` for the configured webhook id.

SAFETY: no test in this module may contact PayPal. Every HTTP interaction is
served by httpx.MockTransport against a reserved ".test" host, an autouse
guard fails the test if any code path tries to open a real socket, and the
ambient PayPal settings (which may hold real sandbox credentials) are blanked
for the duration of the module.
"""

import json
import logging
import uuid

import httpx
import pytest

from app.core.config import settings
from app.gateway.provider import (
    PAYPAL_WEBHOOK_VERIFY_PATH,
    MockPaymentProviderAdapter,
    PayPalSandboxAdapter,
    paypal_sandbox_provider_instance,
)
from app.gateway.webhooks import resolve_webhook_verifier, verify_webhook_signature

FAKE_BASE_URL = "https://paypal-sandbox.test"
TOKEN_PATH = "/v1/oauth2/token"
VERIFY_PATH = PAYPAL_WEBHOOK_VERIFY_PATH

CLIENT_ID = "webhook-test-client-id"
CLIENT_SECRET = "webhook-test-client-secret"
WEBHOOK_ID = "WH-TEST-0001"
ACCESS_TOKEN = "WEBHOOK-ACCESS-TOKEN-SECRET"

TRANSMISSION_HEADERS = {
    "paypal-auth-algo": "SHA256withRSA",
    "paypal-cert-url": "https://api.paypal.com/certs/example",
    "paypal-transmission-id": "transmission-123",
    "paypal-transmission-sig": "transmission-signature-value",
    "paypal-transmission-time": "2026-01-01T00:00:00Z",
}

EVENT_BODY = json.dumps(
    {
        "id": "WH-EVENT-1",
        "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
        "resource": {"batch_header": {"payout_batch_id": "BATCH-1"}},
    }
).encode("utf-8")


class MockPayPal:
    """
    Deterministic PayPal stand-in backed by httpx.MockTransport.

    Behaviour is controlled by the test through explicit attributes so each
    test states exactly what PayPal answers. An unexpected request raises
    immediately instead of silently returning a default.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.verification_status = "SUCCESS"
        self.verification_status_code = 200
        self.verification_body: object = None
        self.verify_error: Exception | None = None
        self.token_error: Exception | None = None
        self.token_status_code = 200

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path == TOKEN_PATH:
            if self.token_error is not None:
                raise self.token_error
            if self.token_status_code != 200:
                return httpx.Response(self.token_status_code, json={"name": "AUTH_FAILURE"})
            return httpx.Response(
                200,
                json={
                    "access_token": ACCESS_TOKEN,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )

        if path == VERIFY_PATH:
            if self.verify_error is not None:
                raise self.verify_error
            if self.verification_body is not None:
                body = self.verification_body
                if isinstance(body, (dict, list)):
                    return httpx.Response(self.verification_status_code, json=body)
                return httpx.Response(self.verification_status_code, text=str(body), headers={})
            return httpx.Response(
                self.verification_status_code,
                json={"verification_status": self.verification_status},
            )

        raise AssertionError(f"Unexpected PayPal request: {request.method} {request.url}")

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def requests_to(self, path: str) -> list[httpx.Request]:
        return [req for req in self.requests if req.url.path == path]


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
def paypal() -> MockPayPal:
    return MockPayPal()


@pytest.fixture
def adapter(paypal: MockPayPal) -> PayPalSandboxAdapter:
    return PayPalSandboxAdapter(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        base_url=FAKE_BASE_URL,
        timeout=5.0,
        webhook_id=WEBHOOK_ID,
        transport=paypal.transport,
    )


@pytest.fixture
def installed_paypal_gateway(paypal: MockPayPal, monkeypatch):
    """
    Point the gateway's webhook verifier at the mocked PayPal.

    The gateway resolves the PayPal adapter singleton, so the singleton is
    reconfigured here (fake credentials, fake host, mocked transport) and the
    original values are restored by monkeypatch afterwards.
    """
    monkeypatch.setattr(paypal_sandbox_provider_instance, "client_id", CLIENT_ID)
    monkeypatch.setattr(paypal_sandbox_provider_instance, "client_secret", CLIENT_SECRET)
    monkeypatch.setattr(paypal_sandbox_provider_instance, "webhook_id", WEBHOOK_ID)
    monkeypatch.setattr(paypal_sandbox_provider_instance, "base_url", FAKE_BASE_URL)
    monkeypatch.setattr(paypal_sandbox_provider_instance, "transport", paypal.transport)
    monkeypatch.setattr(paypal_sandbox_provider_instance, "_token_cache", None)
    return paypal


# ----------------------------------------------------------------------
# Adapter level: incomplete or unverifiable input is rejected
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
def test_missing_transmission_header_is_rejected_without_contacting_paypal(
    adapter, paypal, missing_header
):
    """An incomplete header set can never be verified and is never sent."""
    headers = dict(TRANSMISSION_HEADERS)
    headers.pop(missing_header)

    assert adapter.verify_webhook_signature(headers=headers, raw_body=EVENT_BODY) is False
    assert paypal.requests == []


@pytest.mark.parametrize(
    "credential_field",
    ["client_id", "client_secret", "webhook_id"],
)
def test_unconfigured_verifier_is_rejected_without_contacting_paypal(paypal, credential_field):
    """
    An adapter that is not configured for webhook verification rejects every
    event and never contacts the provider.
    """
    kwargs = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "webhook_id": WEBHOOK_ID,
        "base_url": FAKE_BASE_URL,
        "transport": paypal.transport,
    }
    kwargs[credential_field] = ""
    adapter = PayPalSandboxAdapter(**kwargs)

    assert (
        adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY) is False
    )
    assert paypal.requests == []


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_no_environment_accepts_a_plausible_signature(paypal, monkeypatch, environment):
    """
    Regression: the development fallback accepted any plausible-looking
    signature when the webhook configuration was missing.

    There is no environment in which an unverified signature is accepted.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    adapter = PayPalSandboxAdapter(
        client_id="",
        client_secret="",
        webhook_id="",
        base_url=FAKE_BASE_URL,
        transport=paypal.transport,
    )
    headers = dict(TRANSMISSION_HEADERS)
    headers["paypal-transmission-sig"] = "PLAUSIBLE-LOOKING-SIGNATURE"

    assert adapter.verify_webhook_signature(headers=headers, raw_body=EVENT_BODY) is False
    assert paypal.requests == []


@pytest.mark.parametrize(
    "raw_body",
    [
        b"not-json-at-all",
        b"[1, 2, 3]",
        b'"a string"',
        b"",
    ],
)
def test_unverifiable_event_body_is_rejected_without_contacting_paypal(adapter, paypal, raw_body):
    """Only a JSON object can be verified against the transmitted signature."""
    assert (
        adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=raw_body) is False
    )
    assert paypal.requests == []


# ----------------------------------------------------------------------
# Adapter level: PayPal's own decision is the only source of truth
# ----------------------------------------------------------------------


def test_signature_is_accepted_only_when_paypal_reports_success(adapter, paypal):
    """PayPal's own verification decision is honoured."""
    assert (
        adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY) is True
    )
    assert len(paypal.requests_to(VERIFY_PATH)) == 1


@pytest.mark.parametrize(
    "verification_status",
    ["FAILURE", "PENDING", "UNKNOWN", ""],
)
def test_any_status_other_than_success_is_rejected(adapter, paypal, verification_status):
    """Only the literal SUCCESS status is an acceptance."""
    paypal.verification_status = verification_status

    assert (
        adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY) is False
    )


def test_missing_verification_status_is_rejected(adapter, paypal):
    """A response without a verification status proves nothing."""
    paypal.verification_body = {}

    assert (
        adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY) is False
    )


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 429, 500, 503])
def test_provider_error_status_is_rejected(adapter, paypal, status_code):
    """A provider error never yields a verified webhook."""
    paypal.verification_status_code = status_code

    assert (
        adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY) is False
    )


@pytest.mark.parametrize(
    "body",
    ["<html>not json</html>", "[1, 2, 3]", '"SUCCESS"'],
)
def test_malformed_verification_response_is_rejected(adapter, paypal, body):
    """A non-object or non-JSON verification response is not an acceptance."""
    paypal.verification_body = body

    assert (
        adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY) is False
    )


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectTimeout("timed out"),
        httpx.RemoteProtocolError("peer closed"),
    ],
)
def test_network_and_timeout_errors_are_rejected(adapter, paypal, error):
    """A provider outage must never be treated as a verified webhook."""
    paypal.verify_error = error

    assert (
        adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY) is False
    )


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
    ],
)
def test_token_request_failure_is_rejected(adapter, paypal, error):
    """A failed authentication exchange rejects the webhook."""
    paypal.token_error = error

    assert (
        adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY) is False
    )
    assert paypal.requests_to(VERIFY_PATH) == []


def test_token_request_failure_status_is_rejected(adapter, paypal):
    """A rejected credential exchange rejects the webhook."""
    paypal.token_status_code = 401

    assert (
        adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY) is False
    )
    assert paypal.requests_to(VERIFY_PATH) == []


# ----------------------------------------------------------------------
# Adapter level: the verification request contract
# ----------------------------------------------------------------------


def test_verification_request_carries_the_configured_webhook_id(adapter, paypal):
    """
    The verification request targets PayPal's verification endpoint with the
    configured webhook id.
    """
    adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY)

    requests = paypal.requests_to(VERIFY_PATH)
    assert len(requests) == 1
    assert str(requests[0].url) == f"{FAKE_BASE_URL}{VERIFY_PATH}"
    assert requests[0].method == "POST"

    body = json.loads(requests[0].content)
    assert body["webhook_id"] == WEBHOOK_ID


def test_verification_request_carries_every_transmission_header_value(adapter, paypal):
    """Every transmitted value is forwarded verbatim to the verification API."""
    adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY)

    body = json.loads(paypal.requests_to(VERIFY_PATH)[0].content)
    assert body["auth_algo"] == TRANSMISSION_HEADERS["paypal-auth-algo"]
    assert body["cert_url"] == TRANSMISSION_HEADERS["paypal-cert-url"]
    assert body["transmission_id"] == TRANSMISSION_HEADERS["paypal-transmission-id"]
    assert body["transmission_sig"] == TRANSMISSION_HEADERS["paypal-transmission-sig"]
    assert body["transmission_time"] == TRANSMISSION_HEADERS["paypal-transmission-time"]
    assert body["webhook_event"] == json.loads(EVENT_BODY)


def test_verification_request_is_authenticated_with_a_bearer_token(adapter, paypal):
    """The verification call carries the OAuth bearer token, never the secret."""
    adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY)

    request = paypal.requests_to(VERIFY_PATH)[0]
    assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert CLIENT_SECRET not in request.headers.get("authorization", "")


def test_verification_request_uses_the_mocked_transport_only(adapter, paypal):
    """No real socket is opened during a successful verification."""
    adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY)

    assert [req.url.path for req in paypal.requests] == [TOKEN_PATH, VERIFY_PATH]


def test_header_names_are_matched_case_insensitively(adapter, paypal):
    """PayPal header casing never decides acceptance."""
    upper_headers = {key.upper(): value for key, value in TRANSMISSION_HEADERS.items()}

    assert adapter.verify_webhook_signature(headers=upper_headers, raw_body=EVENT_BODY) is True


# ----------------------------------------------------------------------
# Gateway level: the verifier is never the mock adapter
# ----------------------------------------------------------------------


def test_mock_adapter_never_accepts_a_webhook():
    """
    Regression: the mock adapter accepted any signature that merely looked
    plausible. It must now reject every webhook.
    """
    mock_adapter = MockPaymentProviderAdapter()

    assert (
        mock_adapter.verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY)
        is False
    )
    assert (
        mock_adapter.verify_webhook_signature(
            headers={
                "paypal-auth-algo": "SHA256withRSA",
                "paypal-cert-url": "https://api.paypal.com/certs/example",
                "paypal-transmission-id": "transmission-123",
                "paypal-transmission-sig": "TOTALLY-MADE-UP-SIGNATURE",
                "paypal-transmission-time": "2026-01-01T00:00:00Z",
            },
            raw_body=EVENT_BODY,
        )
        is False
    )


def test_gateway_resolves_the_paypal_verifier_instead_of_the_mock_adapter():
    """Webhook authenticity is verified by PayPal, never by the mock adapter."""
    assert resolve_webhook_verifier() is paypal_sandbox_provider_instance
    assert not isinstance(resolve_webhook_verifier(), MockPaymentProviderAdapter)


def test_gateway_helper_delegates_to_an_injected_verifier():
    """The gateway helper honours an explicitly injected verifier."""
    calls: list[tuple[dict, bytes]] = []

    class StubVerifier:
        def verify_webhook_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
            calls.append((headers, raw_body))
            return True

    assert (
        verify_webhook_signature(
            headers=TRANSMISSION_HEADERS,
            raw_body=EVENT_BODY,
            provider=StubVerifier(),
        )
        is True
    )
    assert calls == [(TRANSMISSION_HEADERS, EVENT_BODY)]


def test_gateway_helper_rejects_when_the_verifier_rejects(installed_paypal_gateway):
    """A failing verification propagates as a rejection."""
    installed_paypal_gateway.verification_status = "FAILURE"

    assert verify_webhook_signature(headers=TRANSMISSION_HEADERS, raw_body=EVENT_BODY) is False


# ----------------------------------------------------------------------
# Route level: the receiver only accepts verified events
# ----------------------------------------------------------------------


def test_verified_webhook_is_processed_and_deduplicated(client, installed_paypal_gateway):
    """A PayPal-verified event is processed once and replayed as a duplicate."""
    event_id = f"WH-{uuid.uuid4()}"
    headers = dict(TRANSMISSION_HEADERS)
    headers["paypal-transmission-id"] = event_id
    payload = {
        "id": event_id,
        "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
        "resource": {"batch_header": {"payout_batch_id": "BATCH-ROUTE-1"}},
    }

    first = client.post("/v1/webhooks/paypal", json=payload, headers=headers)
    second = client.post("/v1/webhooks/paypal", json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json()["status"] == "processed"
    assert first.json()["event_id"] == event_id
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"


def test_verified_webhook_persists_the_platform_merchant_for_deduplication(
    client, installed_paypal_gateway, db_session
):
    """
    Deduplication writes an idempotency row whose merchant_id is a foreign key.

    Regression: the receiver used a hardcoded system UUID that was never
    inserted into `merchants`, so PostgreSQL rejected every verified delivery.
    """
    from sqlalchemy import text

    from app.api.routes.webhooks import WEBHOOK_SYSTEM_MERCHANT_ID
    from app.db.repositories.idempotency_repo import IdempotencyRepository
    from app.models.principal import Merchant

    event_id = f"WH-SYSTEM-MERCHANT-{uuid.uuid4()}"
    payload = {
        "id": event_id,
        "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
        "resource": {},
    }

    # SQLite disables foreign keys by default, which is why the original bug
    # slipped through. Enable them for this delivery so the dedup insert really
    # exercises the merchants foreign key.
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    try:
        res = client.post("/v1/webhooks/paypal", json=payload, headers=dict(TRANSMISSION_HEADERS))
    finally:
        db_session.execute(text("PRAGMA foreign_keys=OFF"))

    assert res.status_code == 200
    merchant = db_session.get(Merchant, WEBHOOK_SYSTEM_MERCHANT_ID)
    assert merchant is not None
    assert merchant.slug == "__identitytwin_webhooks__"
    record = IdempotencyRepository(db_session).get_record(
        WEBHOOK_SYSTEM_MERCHANT_ID, f"paypal-webhook-{event_id}"
    )
    assert record is not None
    assert record.response_payload["event_id"] == event_id


def test_webhook_is_rejected_when_paypal_reports_failure(client, installed_paypal_gateway):
    """A PayPal FAILURE decision is rejected by the receiver."""
    installed_paypal_gateway.verification_status = "FAILURE"
    payload = {"id": f"WH-{uuid.uuid4()}", "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS"}

    res = client.post("/v1/webhooks/paypal", json=payload, headers=dict(TRANSMISSION_HEADERS))

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"


def test_webhook_is_rejected_when_paypal_is_unreachable(client, installed_paypal_gateway):
    """A provider outage rejects the event instead of accepting it."""
    installed_paypal_gateway.verify_error = httpx.ConnectError("connection refused")
    payload = {"id": f"WH-{uuid.uuid4()}", "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS"}

    res = client.post("/v1/webhooks/paypal", json=payload, headers=dict(TRANSMISSION_HEADERS))

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"


def test_webhook_is_rejected_when_the_webhook_id_is_not_configured(
    client, installed_paypal_gateway, monkeypatch
):
    """Without a configured webhook id nothing is verified and nothing is sent."""
    monkeypatch.setattr(paypal_sandbox_provider_instance, "webhook_id", "")
    payload = {"id": f"WH-{uuid.uuid4()}", "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS"}

    res = client.post("/v1/webhooks/paypal", json=payload, headers=dict(TRANSMISSION_HEADERS))

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"
    assert installed_paypal_gateway.requests == []


def test_webhook_is_rejected_when_a_transmission_header_is_missing(
    client, installed_paypal_gateway
):
    """An incomplete header set is rejected before any provider call."""
    headers = dict(TRANSMISSION_HEADERS)
    headers.pop("paypal-transmission-sig")
    payload = {"id": f"WH-{uuid.uuid4()}", "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS"}

    res = client.post("/v1/webhooks/paypal", json=payload, headers=headers)

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"
    assert installed_paypal_gateway.requests == []


def test_forged_webhook_never_reconciles_a_payout(
    client, installed_paypal_gateway, merchant_auth_headers, db_session
):
    """
    A forged event must not be able to flip a payout to "reconciled_completed".
    """
    from app.db.repositories.payout_repo import PayoutRepository

    payout_res = client.post(
        "/v1/payouts",
        json={
            "session_id": "22222222-2222-2222-2222-222222222222",
            "recipient_email": "contractor@supplier.com",
            "amount": 125.00,
            "currency": "USD",
            "reference_note": "Invoice #1",
            "idempotency_key": f"webhook-forgery-{uuid.uuid4()}",
        },
        headers=merchant_auth_headers,
    )
    assert payout_res.status_code == 200
    payout_id = payout_res.json()["payout_id"]
    provider_reference = payout_res.json()["provider_reference"]

    installed_paypal_gateway.verification_status = "FAILURE"
    forged = {
        "id": f"WH-FORGED-{uuid.uuid4()}",
        "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
        "resource": {"batch_header": {"payout_batch_id": provider_reference}},
    }

    res = client.post("/v1/webhooks/paypal", json=forged, headers=dict(TRANSMISSION_HEADERS))

    assert res.status_code == 400
    record = PayoutRepository(db_session).get_by_id(uuid.UUID(str(payout_id)))
    assert record is not None
    assert record.status == "completed"
    assert record.status != "reconciled_completed"


def test_verified_webhook_reconciles_the_payout(
    client, installed_paypal_gateway, merchant_auth_headers, db_session
):
    """A PayPal-verified event still performs the documented reconciliation."""
    from app.db.repositories.payout_repo import PayoutRepository

    payout_res = client.post(
        "/v1/payouts",
        json={
            "session_id": "22222222-2222-2222-2222-222222222222",
            "recipient_email": "contractor@supplier.com",
            "amount": 125.00,
            "currency": "USD",
            "reference_note": "Invoice #2",
            "idempotency_key": f"webhook-reconcile-{uuid.uuid4()}",
        },
        headers=merchant_auth_headers,
    )
    assert payout_res.status_code == 200
    payout_id = payout_res.json()["payout_id"]
    provider_reference = payout_res.json()["provider_reference"]

    verified = {
        "id": f"WH-VERIFIED-{uuid.uuid4()}",
        "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
        "resource": {"batch_header": {"payout_batch_id": provider_reference}},
    }

    res = client.post("/v1/webhooks/paypal", json=verified, headers=dict(TRANSMISSION_HEADERS))

    assert res.status_code == 200
    assert res.json()["status"] == "processed"
    record = PayoutRepository(db_session).get_by_id(uuid.UUID(str(payout_id)))
    assert record is not None
    assert record.status == "reconciled_completed"


def test_webhook_handling_never_logs_credentials_or_sensitive_payloads(
    client, installed_paypal_gateway, caplog
):
    """
    Credentials, the access token, the transmission signature and the event
    payload never reach the logs.
    """
    caplog.set_level(logging.DEBUG)
    event_id = f"WH-{uuid.uuid4()}"
    payload = {
        "id": event_id,
        "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
        "resource": {"batch_header": {"payout_batch_id": "BATCH-LOG-1"}},
    }

    res = client.post("/v1/webhooks/paypal", json=payload, headers=dict(TRANSMISSION_HEADERS))

    assert res.status_code == 200
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert ACCESS_TOKEN not in logged
    assert CLIENT_SECRET not in logged
    assert TRANSMISSION_HEADERS["paypal-transmission-sig"] not in logged
    assert event_id not in logged
    assert "BATCH-LOG-1" not in logged
