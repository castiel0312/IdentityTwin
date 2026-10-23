"""
Gateway Webhook Verification Module.

All payment webhook verification is centralized behind the gateway.
Route handlers outside app/gateway MUST NOT import payment provider adapters directly.
"""

from app.gateway.provider import (
    IPaymentProviderAdapter,
    paypal_sandbox_provider_instance,
)


def resolve_webhook_verifier() -> IPaymentProviderAdapter:
    """
    Resolve the adapter that verifies inbound PayPal webhook signatures.

    Webhook authenticity is verified by PayPal and only by PayPal: the
    signature of an inbound event is checked against PayPal's own
    /v1/notifications/verify-webhook-signature endpoint using the configured
    PAYPAL_WEBHOOK_ID.

    The mock payout adapter is deliberately NOT used here. It cannot verify a
    transmission signature, and accepting a signature on plausibility alone
    would allow an unauthenticated caller to forge payout reconciliation
    events. With no webhook id or no credentials configured, verification
    fails closed and no event is accepted.
    """
    return paypal_sandbox_provider_instance


def verify_webhook_signature(
    headers: dict[str, str],
    raw_body: bytes,
    provider: IPaymentProviderAdapter | None = None,
) -> bool:
    """
    Centralized Trust Gateway webhook cryptographic signature verification.
    Delegates to the configured provider adapter without exposing adapters to route layer.

    Returns True only when the provider confirmed the signature. Any missing
    header, unconfigured verifier, provider error or network failure returns
    False, so callers can treat a False result as "never accept this event".
    """
    adapter = provider or resolve_webhook_verifier()
    return adapter.verify_webhook_signature(headers=headers, raw_body=raw_body)
