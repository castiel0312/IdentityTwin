import os


def get_canary_hmac_secret() -> str:
    secret = (
        os.environ.get("CANARY_HMAC_SECRET")
        or os.environ.get("SECRET_KEY")
        or "dev-canary-secret-change-me"
    )
    return secret


def get_evidence_hmac_key() -> str:
    key = (
        os.environ.get("EVIDENCE_HMAC_KEY")
        or os.environ.get("SECRET_KEY")
        or "dev-evidence-key-change-me"
    )
    return key
