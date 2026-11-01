import os

from app.core.config import (
    has_valid_canary_secret_entropy,
    has_valid_secret_entropy,
    settings,
)


def get_canary_hmac_secret() -> str:
    secret = os.environ.get("CANARY_HMAC_SECRET") or settings.CANARY_HMAC_SECRET
    environment = os.environ.get("ENVIRONMENT", settings.ENVIRONMENT).lower()
    if environment == "production":
        if not has_valid_canary_secret_entropy(secret):
            raise RuntimeError("CANARY_HMAC_SECRET must be configured in production.")
        return secret.strip()
    if secret.strip():
        return secret.strip()

    secret = os.environ.get("SECRET_KEY")
    if secret and secret.strip():
        return secret.strip()
    return "dev-canary-secret-change-me"


def get_evidence_hmac_key() -> str:
    key = os.environ.get("EVIDENCE_HMAC_KEY") or settings.EVIDENCE_HMAC_KEY
    environment = os.environ.get("ENVIRONMENT", settings.ENVIRONMENT).lower()
    if environment == "production":
        if not has_valid_secret_entropy(key):
            raise RuntimeError("EVIDENCE_HMAC_KEY must be configured in production.")
        return key.strip()
    if key.strip():
        return key.strip()

    key = os.environ.get("SECRET_KEY")
    if key and key.strip():
        return key.strip()
    return "dev-evidence-key-change-me"
