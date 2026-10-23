"""
Boundary tests for the PayPal Sandbox base URL allowlist.

IdentityTwin is sandbox-only. ``PAYPAL_BASE_URL`` is validated when Settings is
constructed (application startup, before any provider request can occur) and
again when the PayPal adapter is constructed without an injected test
transport. These tests pin both layers, plus the mocked-transport test seam
that lets the suite use fake hosts without weakening production validation.

SAFETY: no test here talks to PayPal. The adapter-seam test injects an
httpx.MockTransport and asserts that the request is served by it.
"""

import uuid

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import (
    PAYPAL_SANDBOX_BASE_URL,
    PAYPAL_SANDBOX_HOST,
    Settings,
    settings,
    validate_paypal_base_url,
)
from app.gateway.provider import PayPalSandboxAdapter
from app.schemas.payouts import PayoutRequest

APPROVED_URL = PAYPAL_SANDBOX_BASE_URL  # https://api-m.sandbox.paypal.com
MERCHANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def isolate_ambient_paypal_env(monkeypatch):
    """Make the assertions independent of the developer's shell environment."""
    monkeypatch.delenv("PAYPAL_BASE_URL", raising=False)


def make_settings(**overrides) -> Settings:
    """
    Build Settings without reading the repository .env.

    Explicit init kwargs take precedence over environment variables, so the
    assertions below describe configuration validation, not the developer's
    local environment.
    """
    return Settings(_env_file=None, **overrides)


# ----------------------------------------------------------------------
# Settings initialization: the approved Sandbox origin
# ----------------------------------------------------------------------


def test_default_base_url_is_the_official_sandbox_host():
    settings = make_settings()

    assert settings.PAYPAL_BASE_URL == APPROVED_URL
    assert PAYPAL_SANDBOX_HOST == "api-m.sandbox.paypal.com"


def test_explicit_approved_sandbox_url_is_accepted():
    settings = make_settings(PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com")

    assert settings.PAYPAL_BASE_URL == APPROVED_URL


@pytest.mark.parametrize(
    "raw",
    [
        "https://api-m.sandbox.paypal.com/",
        "  https://api-m.sandbox.paypal.com  ",
        "HTTPS://API-M.SANDBOX.PAYPAL.COM",
        "https://api-m.sandbox.paypal.com:443",
    ],
)
def test_equivalent_approved_sandbox_spellings_are_canonicalized(raw):
    """Harmless spelling variants normalize to one canonical origin."""
    assert make_settings(PAYPAL_BASE_URL=raw).PAYPAL_BASE_URL == APPROVED_URL


def test_invalid_base_url_from_the_environment_aborts_settings_initialization(monkeypatch):
    """Startup, not the first payout, is where a bad configuration is rejected."""
    monkeypatch.setenv("PAYPAL_BASE_URL", "https://api-m.paypal.com")

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    assert "not an approved PayPal Sandbox host" in str(excinfo.value)


# ----------------------------------------------------------------------
# Settings initialization: production and lookalike hosts are rejected
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "production_url",
    [
        "https://api-m.paypal.com",
        "https://api.paypal.com",
        "https://www.paypal.com",
        "https://paypal.com",
    ],
)
def test_production_paypal_hosts_are_rejected(production_url):
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYPAL_BASE_URL=production_url)

    assert "not an approved PayPal Sandbox host" in str(excinfo.value)


@pytest.mark.parametrize(
    "lookalike_url",
    [
        # Suffix / prefix lookalikes
        "https://api-m.sandbox.paypal.com.evil.test",
        "https://evil.test.api-m.sandbox.paypal.com",
        "https://api-m.sandbox.paypal.com.evil",
        # Userinfo tricks: the real host would be evil.test
        "https://api-m.sandbox.paypal.com@evil.test",
        "https://evil.test@api-m.sandbox.paypal.com",
        # Trailing-dot FQDN is not byte-identical to the allowlisted host
        "https://api-m.sandbox.paypal.com.",
        # Retired Sandbox host is not the allowlisted official host
        "https://api.sandbox.paypal.com",
        # Homograph: Cyrillic "а" instead of ASCII "a"
        "https://\u0430pi-m.sandbox.paypal.com",
    ],
)
def test_lookalike_and_unexpected_hosts_are_rejected(lookalike_url):
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYPAL_BASE_URL=lookalike_url)

    message = str(excinfo.value)
    assert (
        "not an approved PayPal Sandbox host" in message
        or "must not embed user credentials" in message
        or "bare origin" in message
    )


@pytest.mark.parametrize(
    "insecure_url",
    [
        "http://api-m.sandbox.paypal.com",
        "ftp://api-m.sandbox.paypal.com",
        "ws://api-m.sandbox.paypal.com",
        # Missing scheme
        "api-m.sandbox.paypal.com",
        "//api-m.sandbox.paypal.com",
    ],
)
def test_insecure_and_scheme_less_urls_are_rejected(insecure_url):
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYPAL_BASE_URL=insecure_url)

    assert "must use the https scheme" in str(excinfo.value)


@pytest.mark.parametrize(
    "malformed_url",
    [
        "not a url",
        "https://",
        "https://api-m.sandbox.paypal.com:notaport",
        "https://api-m.sandbox.paypal.com:8443",
        "https://api-m.sandbox.paypal.com/v1",
        "https://api-m.sandbox.paypal.com/paypal-proxy",
        "https://api-m.sandbox.paypal.com?debug=1",
        "https://api-m.sandbox.paypal.com#fragment",
        "https://user:secret@api-m.sandbox.paypal.com",
    ],
)
def test_malformed_or_unsafe_url_shapes_are_rejected(malformed_url):
    with pytest.raises(ValidationError):
        make_settings(PAYPAL_BASE_URL=malformed_url)


@pytest.mark.parametrize("missing", ["", "   ", "\t\n"])
def test_missing_or_blank_base_url_is_rejected(missing):
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYPAL_BASE_URL=missing)

    assert "PAYPAL_BASE_URL is empty" in str(excinfo.value)


# ----------------------------------------------------------------------
# Direct validator contract
# ----------------------------------------------------------------------


def test_validator_returns_the_canonical_url_not_the_raw_input():
    assert validate_paypal_base_url("HTTPS://API-M.SANDBOX.PAYPAL.COM/") == APPROVED_URL


@pytest.mark.parametrize("bad", ["", "http://api-m.sandbox.paypal.com", "https://api-m.paypal.com"])
def test_validator_raises_value_error_for_invalid_values(bad):
    """Settings field validators surface ValueError as ValidationError; keep the
    underlying contract explicit for direct callers."""
    with pytest.raises(ValueError):
        validate_paypal_base_url(bad)


# ----------------------------------------------------------------------
# Adapter layer: defense in depth and the mocked-transport test seam
# ----------------------------------------------------------------------


def test_adapter_accepts_an_explicit_approved_url_without_a_transport():
    adapter = PayPalSandboxAdapter(
        client_id="test-client-id",
        client_secret="test-client-secret",
        base_url=APPROVED_URL,
    )

    assert adapter.base_url == APPROVED_URL


def test_adapter_rejects_a_production_url_without_a_test_transport():
    """No transport means real network access: the host must be allowlisted."""
    with pytest.raises(ValueError) as excinfo:
        PayPalSandboxAdapter(
            client_id="test-client-id",
            client_secret="test-client-secret",
            base_url="https://api-m.paypal.com",
        )

    assert "not an approved PayPal Sandbox host" in str(excinfo.value)


def test_adapter_rejects_a_production_url_even_with_a_real_http_transport():
    """
    Injecting the real transport is not a test seam: it would still reach the
    network, so the allowlist stays enforced.
    """
    with pytest.raises(ValueError) as excinfo:
        PayPalSandboxAdapter(
            client_id="test-client-id",
            client_secret="test-client-secret",
            base_url="https://api-m.paypal.com",
            transport=httpx.HTTPTransport(),
        )

    assert "not an approved PayPal Sandbox host" in str(excinfo.value)


def test_adapter_rejects_an_insecure_url_without_a_test_transport():
    with pytest.raises(ValueError):
        PayPalSandboxAdapter(
            client_id="test-client-id",
            client_secret="test-client-secret",
            base_url="http://api-m.sandbox.paypal.com",
        )


def test_adapter_rejects_an_invalid_ambient_setting_at_construction(monkeypatch):
    """
    Runtime mutation of settings (as tests do) cannot smuggle a production host
    into an adapter that would use the real network.
    """
    monkeypatch.setattr(settings, "PAYPAL_BASE_URL", "https://api-m.paypal.com")

    with pytest.raises(ValueError) as excinfo:
        PayPalSandboxAdapter(client_id="test-client-id", client_secret="test-client-secret")

    assert "not an approved PayPal Sandbox host" in str(excinfo.value)


def test_injected_mock_transport_permits_a_fake_host_and_never_reaches_the_network():
    """
    The test seam: a mocked transport keeps every byte inside the process, so a
    fake host is acceptable. This is the only way to bypass the allowlist.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "TEST-TOKEN", "expires_in": 3600})
        return httpx.Response(
            201, json={"batch_header": {"payout_batch_id": "BATCH-TEST", "batch_status": "PENDING"}}
        )

    adapter = PayPalSandboxAdapter(
        client_id="test-client-id",
        client_secret="test-client-secret",
        base_url="https://paypal-sandbox.test",
        transport=httpx.MockTransport(handler),
    )

    assert adapter.base_url == "https://paypal-sandbox.test"

    request = PayoutRequest(
        session_id="22222222-2222-2222-2222-222222222222",
        recipient_email="payee@example.com",
        amount=10.0,
        currency="USD",
        idempotency_key="boundary-test-key",
    )
    result = adapter.execute_payout(request, MERCHANT_ID)

    assert result.provider_transaction_id == "BATCH-TEST"
    assert [r.url.host for r in seen] == ["paypal-sandbox.test", "paypal-sandbox.test"]
    assert all(r.url.scheme == "https" for r in seen)
