"""
Gateway Webhook Verification Module.

All payment webhook verification is centralized behind the gateway.
Route handlers outside app/gateway MUST NOT import payment provider adapters directly.
"""

from app.gateway.provider import IPaymentProviderAdapter, get_payment_provider


def verify_webhook_signature(
    headers: dict[str, str],
    raw_body: bytes,
    provider: IPaymentProviderAdapter | None = None,
) -> bool:
    """
    Centralized Trust Gateway webhook cryptographic signature verification.
    Delegates to configured provider adapter without exposing adapters to route layer.
    """
    adapter = provider or get_payment_provider()
    return adapter.verify_webhook_signature(headers=headers, raw_body=raw_body)
