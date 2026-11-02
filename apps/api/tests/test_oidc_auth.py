import secrets
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import security
from app.core.config import Settings, settings
from app.core.exceptions import AuthenticationRequiredException
from app.core.security import RoleEnum, _extract_principal_from_claims, _validate_jwt_token
from tests.conftest import OTHER_MERCHANT_ID, TEST_MERCHANT_ID


def _production_settings(**overrides) -> Settings:
    values = {
        "ENVIRONMENT": "production",
        "ALLOW_DEV_AUTH": False,
        "CANARY_HMAC_SECRET": secrets.token_urlsafe(48),
        "EVIDENCE_HMAC_KEY": secrets.token_urlsafe(48),
        "DATABASE_URL": "postgresql+psycopg://user:pass@db.example.com/identitytwin",
        "OIDC_ISSUER_URL": "https://issuer.example.com",
        "OIDC_AUDIENCE": "identitytwin-api",
        "PAYMENT_PROVIDER": "mock",
        "PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_settings_do_not_require_dev_auth_token():
    configured = _production_settings()
    assert configured.ALLOW_DEV_AUTH is False
    assert configured.DEV_AUTH_TOKEN == ""


@pytest.mark.parametrize("algorithm", ["none", "HS256", "RS256,HS256", ""])
def test_unsafe_oidc_algorithms_abort_startup(algorithm: str):
    with pytest.raises(ValidationError):
        _production_settings(OIDC_ALGORITHMS=algorithm)


def test_production_oidc_urls_must_be_https():
    with pytest.raises(ValidationError):
        _production_settings(OIDC_ISSUER_URL="http://issuer.example.com")
    with pytest.raises(ValidationError):
        _production_settings(OIDC_JWKS_URL="http://issuer.example.com/jwks.json")


def test_admin_role_takes_precedence_over_analyst():
    principal = _extract_principal_from_claims(
        {
            "sub": "user-123",
            "email": "admin@example.com",
            "roles": ["analyst", "ADMIN"],
            "merchant_id": str(TEST_MERCHANT_ID),
        }
    )
    assert principal.role is RoleEnum.ADMIN
    assert principal.merchant_id == TEST_MERCHANT_ID
    assert principal.auth_method == "oidc_jwt"


def test_analyst_role_is_mapped_without_merchant_escalation():
    principal = _extract_principal_from_claims(
        {
            "sub": "user-123",
            "email": "analyst@example.com",
            "roles": ["analyst"],
            "merchant_id": str(TEST_MERCHANT_ID),
        }
    )
    assert principal.role is RoleEnum.ANALYST


def test_unknown_role_defaults_to_least_privilege_merchant():
    principal = _extract_principal_from_claims(
        {
            "sub": "user-123",
            "email": "user@example.com",
            "roles": ["unknown-role"],
            "merchant_id": str(TEST_MERCHANT_ID),
        }
    )
    assert principal.role is RoleEnum.MERCHANT


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "", "email": "user@example.com", "roles": [], "merchant_id": str(TEST_MERCHANT_ID)},
        {"sub": "u", "email": "", "roles": [], "merchant_id": str(TEST_MERCHANT_ID)},
        {"sub": "u", "email": "user@example.com", "roles": "analyst", "merchant_id": str(TEST_MERCHANT_ID)},
        {"sub": "u", "email": "user@example.com", "roles": [1], "merchant_id": str(TEST_MERCHANT_ID)},
        {"sub": "u", "email": "user@example.com", "roles": []},
        {"sub": "u", "email": "user@example.com", "roles": [], "merchant_id": "not-a-uuid"},
    ],
)
def test_malformed_oidc_claims_fail_closed(claims: dict):
    with pytest.raises(AuthenticationRequiredException):
        _extract_principal_from_claims(claims)


def test_arbitrary_dev_prefix_token_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "ALLOW_DEV_AUTH", True)
    response = client.get(
        "/v1/sessions", headers={"Authorization": "Bearer dev-attacker-token"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_production_endpoint_uses_validated_oidc_claims(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "ALLOW_DEV_AUTH", False)
    claims = {
        "sub": "user-123",
        "email": "analyst@example.com",
        "roles": ["analyst"],
        "merchant_id": str(TEST_MERCHANT_ID),
    }
    with patch("app.core.security._validate_jwt_token", return_value=claims):
        response = client.get(
            "/v1/sessions", headers={"Authorization": "Bearer signed.jwt.token"}
        )
    assert response.status_code == 200, response.text


def test_oidc_merchant_scope_cannot_cross_tenants(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "ALLOW_DEV_AUTH", False)
    claims = {
        "sub": "user-123",
        "email": "analyst@example.com",
        "roles": ["analyst"],
        "merchant_id": str(OTHER_MERCHANT_ID),
    }
    with patch("app.core.security._validate_jwt_token", return_value=claims):
        response = client.get(
            "/v1/sessions/22222222-2222-2222-2222-222222222222",
            headers={"Authorization": "Bearer signed.jwt.token"},
        )
    assert response.status_code in (403, 404)


def test_jwks_failure_fails_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "OIDC_ISSUER_URL", "https://issuer.example.com")
    monkeypatch.setattr(
        security, "_get_jwks_client", lambda: (_ for _ in ()).throw(RuntimeError("jwks down"))
    )
    with pytest.raises(AuthenticationRequiredException):
        _validate_jwt_token("signed.jwt.token")


def test_jwt_decode_uses_configured_algorithms_and_required_claims(
    monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "OIDC_ALGORITHMS", ["RS256", "ES256"])
    monkeypatch.setattr(settings, "OIDC_AUDIENCE", "identitytwin-api")
    monkeypatch.setattr(settings, "OIDC_ISSUER_URL", "https://issuer.example.com")
    monkeypatch.setattr(settings, "OIDC_REQUIRED_CLAIMS", ["sub", "email", "roles"])
    captured: dict = {}

    class _Key:
        key = "public-key"

    class _Client:
        def get_signing_key_from_jwt(self, token: str):
            return _Key()

    def _decode(token, key, **kwargs):
        captured.update(kwargs)
        return {"sub": "u", "email": "user@example.com", "roles": []}

    monkeypatch.setattr(security, "_get_jwks_client", lambda: _Client())
    monkeypatch.setattr(security.jwt, "decode", _decode)

    assert _validate_jwt_token("token")["sub"] == "u"
    assert captured["algorithms"] == ["RS256", "ES256"]
    assert captured["audience"] == "identitytwin-api"
    assert captured["issuer"] == "https://issuer.example.com"
    assert captured["options"]["require"] == ["sub", "email", "roles"]
