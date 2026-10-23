"""
Startup readiness tests for payment provider selection.

``PAYMENT_PROVIDER`` is an exhaustive choice: ``mock`` or ``paypal_sandbox``.
The offline mock workflow needs no PayPal credentials, but selecting the live
Sandbox adapter without a nonblank Client ID and Secret is a startup
configuration error rather than a failure deferred to the first payout.
Unknown values are rejected outright and are never silently mapped to mock.

SAFETY: no test here contacts PayPal. Adapter selection only returns singleton
instances, and an autouse guard fails the test if a real HTTP request is made.
"""

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import (
    ALLOWED_PAYMENT_PROVIDERS,
    PAYMENT_PROVIDER_MOCK,
    PAYMENT_PROVIDER_PAYPAL_SANDBOX,
    PAYPAL_SANDBOX_BASE_URL,
    Settings,
    settings,
)
from app.core.exceptions import IdentityTwinException
from app.gateway.provider import (
    MockPaymentProviderAdapter,
    PayPalSandboxAdapter,
    get_payment_provider,
)

# Distinctive values so leakage assertions cannot pass by accident.
CLIENT_ID = "test-client-id-DO-NOT-LEAK"
CLIENT_SECRET = "test-client-secret-DO-NOT-LEAK"
CREDENTIALS = {"PAYPAL_CLIENT_ID": CLIENT_ID, "PAYPAL_CLIENT_SECRET": CLIENT_SECRET}


@pytest.fixture(autouse=True)
def isolate_ambient_provider_env(monkeypatch):
    """Keep assertions independent of the developer's shell environment."""
    for name in (
        "PAYMENT_PROVIDER",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def forbid_real_http(monkeypatch):
    """Fail loudly if any test in this module attempts a real request."""

    def _blocked(*args, **kwargs):
        raise AssertionError("test attempted a real HTTP request")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)


def make_settings(**overrides) -> Settings:
    """Build Settings without reading the repository .env file."""
    return Settings(_env_file=None, **overrides)


# ----------------------------------------------------------------------
# Exhaustive provider allowlist
# ----------------------------------------------------------------------


def test_allowed_provider_set_is_exhaustive():
    assert ALLOWED_PAYMENT_PROVIDERS == frozenset({"mock", "paypal_sandbox"})


def test_default_provider_is_mock():
    assert make_settings().PAYMENT_PROVIDER == PAYMENT_PROVIDER_MOCK


def test_explicit_mock_is_accepted():
    assert make_settings(PAYMENT_PROVIDER="mock").PAYMENT_PROVIDER == "mock"


@pytest.mark.parametrize("value", [" mock ", "MOCK", "Mock\n", "\tmock"])
def test_provider_spelling_is_normalized(value):
    assert make_settings(PAYMENT_PROVIDER=value).PAYMENT_PROVIDER == "mock"


@pytest.mark.parametrize("value", [" PayPal_Sandbox ", "PAYPAL_SANDBOX"])
def test_paypal_provider_spelling_is_normalized(value):
    result = make_settings(PAYMENT_PROVIDER=value, **CREDENTIALS)
    assert result.PAYMENT_PROVIDER == PAYMENT_PROVIDER_PAYPAL_SANDBOX


@pytest.mark.parametrize(
    "value",
    ["stripe", "paypal", "live", "paypal-production", "mock2", "none", "false"],
)
def test_unknown_provider_values_are_rejected(value):
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYMENT_PROVIDER=value)

    message = str(excinfo.value)
    assert "PAYMENT_PROVIDER must be one of" in message
    assert "'mock'" in message and "'paypal_sandbox'" in message
    assert "silently falling back" in message


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_empty_provider_is_rejected(value):
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYMENT_PROVIDER=value)

    assert "PAYMENT_PROVIDER must be one of" in str(excinfo.value)


@pytest.mark.parametrize("value", [None, 123, ["mock"], {"provider": "mock"}])
def test_non_string_provider_is_rejected(value):
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYMENT_PROVIDER=value)

    assert "got a non-string value" in str(excinfo.value)


# ----------------------------------------------------------------------
# Credential readiness for the live Sandbox adapter
# ----------------------------------------------------------------------


def test_paypal_sandbox_with_valid_credentials_is_accepted():
    result = make_settings(PAYMENT_PROVIDER="paypal_sandbox", **CREDENTIALS)

    assert result.PAYMENT_PROVIDER == "paypal_sandbox"
    assert result.PAYPAL_CLIENT_ID == CLIENT_ID
    assert result.PAYPAL_CLIENT_SECRET == CLIENT_SECRET


def test_paypal_sandbox_requires_both_credentials():
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYMENT_PROVIDER="paypal_sandbox")

    message = str(excinfo.value)
    assert "credentials are missing or blank" in message
    assert "PAYPAL_CLIENT_ID" in message
    assert "PAYPAL_CLIENT_SECRET" in message


def test_paypal_sandbox_requires_client_id_when_only_secret_is_set():
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYMENT_PROVIDER="paypal_sandbox", PAYPAL_CLIENT_SECRET=CLIENT_SECRET)

    message = str(excinfo.value)
    assert "PAYPAL_CLIENT_ID" in message
    assert "PAYPAL_CLIENT_SECRET" not in message


def test_paypal_sandbox_requires_client_secret_when_only_id_is_set():
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYMENT_PROVIDER="paypal_sandbox", PAYPAL_CLIENT_ID=CLIENT_ID)

    message = str(excinfo.value)
    assert "PAYPAL_CLIENT_SECRET" in message
    assert "PAYPAL_CLIENT_ID" not in message


@pytest.mark.parametrize(
    "blank",
    ["", " ", "\t", "\n  \t"],
)
def test_paypal_sandbox_rejects_blank_credentials(blank):
    with pytest.raises(ValidationError) as excinfo:
        make_settings(
            PAYMENT_PROVIDER="paypal_sandbox",
            PAYPAL_CLIENT_ID=blank,
            PAYPAL_CLIENT_SECRET=blank,
        )

    assert "credentials are missing or blank" in str(excinfo.value)


def test_mock_provider_does_not_require_credentials():
    result = make_settings(PAYMENT_PROVIDER="mock", PAYPAL_CLIENT_ID="", PAYPAL_CLIENT_SECRET="")

    assert result.PAYMENT_PROVIDER == "mock"
    assert result.PAYPAL_CLIENT_ID == ""
    assert result.PAYPAL_CLIENT_SECRET == ""


# ----------------------------------------------------------------------
# Secrets never appear in configuration errors
# ----------------------------------------------------------------------


def test_missing_credential_error_does_not_leak_the_configured_value():
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYMENT_PROVIDER="paypal_sandbox", PAYPAL_CLIENT_ID=CLIENT_ID)

    error = excinfo.value
    rendered = str(error) + repr(error.errors())
    assert CLIENT_ID not in rendered
    assert "PAYPAL_CLIENT_SECRET" in str(error)


def test_unknown_provider_error_does_not_leak_configured_credentials():
    with pytest.raises(ValidationError) as excinfo:
        make_settings(PAYMENT_PROVIDER="stripe", **CREDENTIALS)

    error = excinfo.value
    rendered = str(error) + repr(error.errors())
    assert CLIENT_ID not in rendered
    assert CLIENT_SECRET not in rendered


# ----------------------------------------------------------------------
# Environment variables take effect at Settings construction
# ----------------------------------------------------------------------


def test_env_unknown_provider_aborts_settings_construction(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "stripe")

    with pytest.raises(ValidationError) as excinfo:
        make_settings()

    assert "PAYMENT_PROVIDER must be one of" in str(excinfo.value)


def test_env_paypal_sandbox_without_credentials_aborts_settings_construction(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "paypal_sandbox")

    with pytest.raises(ValidationError) as excinfo:
        make_settings()

    assert "credentials are missing or blank" in str(excinfo.value)


def test_env_paypal_sandbox_with_credentials_is_accepted(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "paypal_sandbox")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", CLIENT_SECRET)

    result = make_settings()

    assert result.PAYMENT_PROVIDER == "paypal_sandbox"


def test_env_mock_without_credentials_is_accepted(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")

    assert make_settings().PAYMENT_PROVIDER == "mock"


# ----------------------------------------------------------------------
# The Sandbox host allowlist still applies when the live adapter is selected
# ----------------------------------------------------------------------


def test_paypal_sandbox_with_production_base_url_is_still_rejected():
    with pytest.raises(ValidationError) as excinfo:
        make_settings(
            PAYMENT_PROVIDER="paypal_sandbox",
            PAYPAL_BASE_URL="https://api-m.paypal.com",
            **CREDENTIALS,
        )

    assert "not an approved PayPal Sandbox host" in str(excinfo.value)


def test_paypal_sandbox_with_approved_base_url_is_accepted():
    result = make_settings(
        PAYMENT_PROVIDER="paypal_sandbox",
        PAYPAL_BASE_URL=PAYPAL_SANDBOX_BASE_URL,
        **CREDENTIALS,
    )

    assert result.PAYPAL_BASE_URL == PAYPAL_SANDBOX_BASE_URL


# ----------------------------------------------------------------------
# Adapter selection (defense in depth for runtime mutation)
# ----------------------------------------------------------------------


def test_get_payment_provider_returns_mock_by_default():
    assert isinstance(get_payment_provider(), MockPaymentProviderAdapter)


def test_get_payment_provider_returns_paypal_adapter_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "paypal_sandbox")

    assert isinstance(get_payment_provider(), PayPalSandboxAdapter)


def test_get_payment_provider_rejects_unknown_value_at_runtime(monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "stripe")

    with pytest.raises(IdentityTwinException) as excinfo:
        get_payment_provider()

    error = excinfo.value
    assert error.code == "PAYMENT_PROVIDER_UNKNOWN"
    assert error.status_code == 500
    assert "stripe" in error.message
    assert "Allowed values: 'mock', 'paypal_sandbox'" in error.message


def test_get_payment_provider_normalizes_runtime_spelling(monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "  MOCK  ")

    assert isinstance(get_payment_provider(), MockPaymentProviderAdapter)
