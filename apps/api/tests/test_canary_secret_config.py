import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.secrets import get_canary_hmac_secret, get_evidence_hmac_key

PRODUCTION_SETTINGS = {
    "ENVIRONMENT": "production",
    "ALLOW_DEV_AUTH": False,
    "DATABASE_URL": "postgresql+psycopg://user:pass@localhost/identitytwin",
    "OIDC_ISSUER_URL": "https://issuer.example.com",
    "OIDC_AUDIENCE": "identitytwin-api",
    "DEV_AUTH_TOKEN": "explicit-production-value",
    "PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE": True,
    "EVIDENCE_HMAC_KEY": "EviD3nce-HMAC-Key-9xR4mV7qL2sK8wT5",
}


@pytest.mark.parametrize(
    "secret",
    ["", "short", "dev-canary-secret-change-me", "a" * 48],
)
def test_production_requires_a_non_development_canary_secret(secret):
    with pytest.raises(ValidationError, match="CANARY_HMAC_SECRET"):
        Settings(_env_file=None, **PRODUCTION_SETTINGS, CANARY_HMAC_SECRET=secret)


def test_production_accepts_an_explicit_high_entropy_canary_secret():
    configured = Settings(
        _env_file=None,
        **PRODUCTION_SETTINGS,
        CANARY_HMAC_SECRET="A9kL2pQ7wX4zB6nM8rT1cV5yD3fG0hJ2",
    )

    assert configured.CANARY_HMAC_SECRET == "A9kL2pQ7wX4zB6nM8rT1cV5yD3fG0hJ2"


def test_secret_getter_never_uses_development_fallback_in_production(monkeypatch):
    monkeypatch.setattr("app.core.secrets.settings.CANARY_HMAC_SECRET", "")
    monkeypatch.setattr("app.core.secrets.settings.ENVIRONMENT", "production")
    monkeypatch.delenv("CANARY_HMAC_SECRET", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="CANARY_HMAC_SECRET"):
        get_canary_hmac_secret()


@pytest.mark.parametrize("secret", ["", "short", "dev-evidence-key-change-me", "a" * 48])
def test_production_requires_a_non_development_evidence_key(secret):
    production_settings = {**PRODUCTION_SETTINGS, "EVIDENCE_HMAC_KEY": secret}
    with pytest.raises(ValidationError, match="EVIDENCE_HMAC_KEY"):
        Settings(
            _env_file=None,
            **production_settings,
            CANARY_HMAC_SECRET="A9kL2pQ7wX4zB6nM8rT1cV5yD3fG0hJ2",
        )


def test_evidence_secret_getter_never_uses_development_fallback_in_production(monkeypatch):
    monkeypatch.setattr("app.core.secrets.settings.EVIDENCE_HMAC_KEY", "")
    monkeypatch.setattr("app.core.secrets.settings.ENVIRONMENT", "production")
    monkeypatch.delenv("EVIDENCE_HMAC_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="EVIDENCE_HMAC_KEY"):
        get_evidence_hmac_key()
