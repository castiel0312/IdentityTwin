"""Conservative redaction helpers for projections returned to the console.

The console is an operator surface, not an evidence export: payment secrets,
provider credentials and authentication material must never be projected into a
response, an error message or a client-side log.
"""

from typing import Any

_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "client_secret",
    "secret",
    "password",
    "token",
    "api_key",
    "access_key",
    "private_key",
    "card",
    "cvv",
    "cvc",
    "iban",
    "account_number",
    "webhook",
)

REDACTED = "[REDACTED]"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def redact(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact sensitive mapping keys while preserving structure."""
    if depth > 8:
        return REDACTED
    if isinstance(value, dict):
        return {
            key: (REDACTED if _is_sensitive(str(key)) else redact(item, depth=depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, depth=depth + 1) for item in value[:200]]
    return value
