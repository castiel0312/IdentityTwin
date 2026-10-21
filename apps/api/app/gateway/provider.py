import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationRequiredException,
    PaymentProviderException,
    ProviderRateLimitException,
    ProviderTimeoutException,
)
from app.schemas.payouts import PayoutRequest


class ProviderPayoutResult(BaseModel):
    success: bool
    provider_name: str
    provider_transaction_id: str
    environment: str = Field(
        description="Environment indicator, e.g. 'synthetic_mock' or 'paypal_sandbox'"
    )
    details: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime


class IPaymentProviderAdapter(Protocol):
    """Protocol for protected payment provider adapters."""

    def execute_payout(self, request: PayoutRequest, merchant_id: UUID) -> ProviderPayoutResult: ...

    def verify_webhook_signature(self, headers: dict[str, str], raw_body: bytes) -> bool: ...


class MockPaymentProviderAdapter:
    """
    Safe mock adapter for automated testing and local development.

    CRITICAL INVARIANT:
    Returns unmistakably synthetic transaction references.
    Must NEVER claim a real PayPal transaction occurred.
    """

    def __init__(self):
        self.invocation_count = 0
        self.executed_transactions = []

    def reset(self) -> None:
        self.invocation_count = 0
        self.executed_transactions.clear()

    def execute_payout(self, request: PayoutRequest, merchant_id: UUID) -> ProviderPayoutResult:
        self.invocation_count += 1
        synth_tx_id = f"SYNTH-MOCK-TXN-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)

        result = ProviderPayoutResult(
            success=True,
            provider_name="mock_adapter",
            provider_transaction_id=synth_tx_id,
            environment="synthetic_mock",
            details={
                "mock_warning": "SYNTHETIC SIMULATION ONLY. NO REAL MONEY MOVED.",
                "recipient": request.recipient_email,
                "amount": request.amount,
                "currency": request.currency,
                "merchant_id": str(merchant_id),
                "invocation_number": self.invocation_count,
            },
            executed_at=now,
        )
        self.executed_transactions.append(result)
        return result

    def verify_webhook_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        # Normalized header lookup
        normalized = {k.lower(): v for k, v in headers.items()}
        sig = normalized.get("paypal-transmission-sig", "")
        algo = normalized.get("paypal-auth-algo", "")
        cert = normalized.get("paypal-cert-url", "")
        trans_id = normalized.get("paypal-transmission-id", "")
        if not sig or not algo or not cert or not trans_id:
            return False
        if sig == "INVALID_SIGNATURE" or "invalid" in sig.lower():
            return False
        return True


class DecoyHoneyAdapter:
    """
    Synthetic honey-workspace provider adapter.
    Handles sessions routed to DECOY.
    Never moves funds or contacts PayPal.
    """

    def __init__(self):
        self.invocation_count = 0

    def execute_decoy(self, request: PayoutRequest, merchant_id: UUID) -> ProviderPayoutResult:
        self.invocation_count += 1
        decoy_tx_id = f"HONEY-DECOY-SIM-TXN-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)

        return ProviderPayoutResult(
            success=True,
            provider_name="honey_synthetic_decoy",
            provider_transaction_id=decoy_tx_id,
            environment="honey_sandbox_simulation",
            details={
                "honey_warning": "CONFINEMENT SIMULATION. DECOY WORKSPACE ENGAGED.",
                "recipient": request.recipient_email,
                "amount": request.amount,
                "currency": request.currency,
                "merchant_id": str(merchant_id),
            },
            executed_at=now,
        )


class PayPalSandboxAdapter:
    """
    Production-grade PayPal Sandbox REST adapter for IdentityTwin.

    Connects to official PayPal Sandbox endpoints:
    - OAuth2 Token: POST /v1/oauth2/token
    - Payouts Execution: POST /v1/payments/payouts
    - Webhook Verification: POST /v1/notifications/verify-webhook-signature

    CRITICAL SECURITY INVARIANTS:
    1. Operates exclusively against PayPal Sandbox (never production credentials).
    2. Uses PayPal-Request-Id header for provider-level idempotency to prevent double-execution.
    3. Never logs access tokens, client secrets, or full payment authorization headers.
    4. Explicit timeout enforcement and granular error status mapping.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        webhook_id: str | None = None,
    ):
        self.client_id = client_id or settings.PAYPAL_CLIENT_ID
        self.client_secret = client_secret or settings.PAYPAL_CLIENT_SECRET
        self.base_url = (base_url or settings.PAYPAL_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.PAYPAL_REQUEST_TIMEOUT
        self.webhook_id = webhook_id or settings.PAYPAL_WEBHOOK_ID
        self._token_cache: tuple[str, float] | None = None  # (token, expires_at_epoch)

    def _get_access_token(self) -> str:
        """
        Obtains or refreshes an OAuth2 client credentials bearer token from PayPal Sandbox.
        Caches token until 60 seconds before expiration.
        """
        if not self.client_id or not self.client_secret:
            raise AuthenticationRequiredException(
                message=(
                    "PayPal Sandbox credentials are not configured. "
                    "Please set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env."
                ),
                code="PAYPAL_CREDENTIALS_MISSING",
            )

        now = time.time()
        if self._token_cache:
            token, expires_at = self._token_cache
            if now < expires_at - 60:
                return token

        token_url = f"{self.base_url}/v1/oauth2/token"
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US",
        }
        data = {"grant_type": "client_credentials"}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(
                    token_url,
                    auth=(self.client_id, self.client_secret),
                    headers=headers,
                    data=data,
                )
        except httpx.TimeoutException:
            raise ProviderTimeoutException(
                message="PayPal OAuth access token request timed out.",
                code="PAYPAL_OAUTH_TIMEOUT",
            ) from None
        except httpx.RequestError as exc:
            raise PaymentProviderException(
                message=f"Network error during PayPal OAuth authentication: {type(exc).__name__}",
                code="PAYPAL_NETWORK_ERROR",
            ) from None

        if res.status_code == 401 or res.status_code == 403:
            raise AuthenticationRequiredException(
                message="PayPal Sandbox rejected authentication credentials (invalid client_id or secret).",
                code="PAYPAL_AUTHENTICATION_FAILED",
            )
        elif res.status_code != 200:
            raise PaymentProviderException(
                message=f"PayPal OAuth token endpoint returned unexpected HTTP status {res.status_code}.",
                code="PAYPAL_OAUTH_ERROR",
            )

        token_data = res.json()
        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 32400)
        if not access_token:
            raise PaymentProviderException(
                message="PayPal OAuth response missing access_token field.",
                code="PAYPAL_OAUTH_INVALID_PAYLOAD",
            )

        self._token_cache = (access_token, now + expires_in)
        return access_token

    def execute_payout(self, request: PayoutRequest, merchant_id: UUID) -> ProviderPayoutResult:
        """
        Executes payout using PayPal Sandbox Payouts API (/v1/payments/payouts).
        Sends PayPal-Request-Id header for idempotency protection.
        """
        token = self._get_access_token()
        payouts_url = f"{self.base_url}/v1/payments/payouts"

        sender_batch_id = f"IDTWIN-{uuid.uuid4().hex[:12].upper()}"
        sender_item_id = f"ITEM-{uuid.uuid4().hex[:12].upper()}"

        payload = {
            "sender_batch_header": {
                "sender_batch_id": sender_batch_id,
                "email_subject": "IdentityTwin Protected Disbursement",
                "email_message": request.reference_note
                or "IdentityTwin verified merchant payout through Trust Gateway.",
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {
                        "value": f"{request.amount:.2f}",
                        "currency": request.currency,
                    },
                    "note": request.reference_note or "Protected payout",
                    "sender_item_id": sender_item_id,
                    "receiver": request.recipient_email,
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": request.idempotency_key,
        }

        now_executed = datetime.now(timezone.utc)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(payouts_url, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise ProviderTimeoutException(
                message="PayPal Sandbox payout request timed out. Outcome is ambiguous and requires reconciliation.",
                code="PAYPAL_PAYOUT_TIMEOUT",
                details={"idempotency_key": request.idempotency_key},
            ) from None
        except httpx.RequestError as exc:
            raise PaymentProviderException(
                message=f"Network communication failure with PayPal Sandbox: {type(exc).__name__}",
                code="PAYPAL_NETWORK_FAILURE",
            ) from None

        if res.status_code == 429:
            raise ProviderRateLimitException(
                message="PayPal Sandbox rate limit exceeded. Retry later.",
                code="PAYPAL_RATE_LIMIT",
            )
        elif res.status_code == 401:
            # Token might have expired early or been revoked; invalidate cache
            self._token_cache = None
            raise AuthenticationRequiredException(
                message="PayPal Sandbox rejected authentication token for payout execution.",
                code="PAYPAL_TOKEN_INVALID",
            )
        elif res.status_code == 400 or res.status_code == 422:
            try:
                err_data = res.json()
            except Exception:
                err_data = {"raw": res.text[:200]}
            err_name = err_data.get("name") or "UNPROCESSABLE_ENTITY"
            err_msg = err_data.get("message") or "PayPal payout was rejected by sandbox policy."
            raise PaymentProviderException(
                message=f"PayPal Sandbox payout rejected: {err_name} - {err_msg}",
                code="PAYPAL_PAYOUT_REJECTED",
                details={
                    "paypal_error_name": err_name,
                    "details": err_data.get("details", []),
                },
            )
        elif res.status_code not in (200, 201):
            raise PaymentProviderException(
                message=f"PayPal Sandbox returned unexpected status {res.status_code}.",
                code="PAYPAL_UNEXPECTED_RESPONSE",
                details={"status_code": res.status_code},
            )

        res_data = res.json()
        batch_header = res_data.get("batch_header", {})
        payout_batch_id = batch_header.get("payout_batch_id") or sender_batch_id
        batch_status = batch_header.get("batch_status", "PENDING")

        return ProviderPayoutResult(
            success=True,
            provider_name="paypal_sandbox",
            provider_transaction_id=payout_batch_id,
            environment="paypal_sandbox",
            details={
                "batch_status": batch_status,
                "sender_batch_id": sender_batch_id,
                "time_created": batch_header.get("time_created"),
                "time_completed": batch_header.get("time_completed"),
                "recipient": request.recipient_email,
                "amount": request.amount,
                "currency": request.currency,
                "merchant_id": str(merchant_id),
            },
            executed_at=now_executed,
        )

    def verify_webhook_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        """
        Verifies PayPal webhook signature via POST /v1/notifications/verify-webhook-signature.
        """
        normalized = {k.lower(): v for k, v in headers.items()}
        auth_algo = normalized.get("paypal-auth-algo")
        cert_url = normalized.get("paypal-cert-url")
        trans_id = normalized.get("paypal-transmission-id")
        trans_sig = normalized.get("paypal-transmission-sig")
        trans_time = normalized.get("paypal-transmission-time")

        if not all([auth_algo, cert_url, trans_id, trans_sig, trans_time]):
            return False

        # When credentials/webhook id are missing, reject unless in development mode
        if not self.client_id or not self.client_secret or not self.webhook_id:
            if settings.ENVIRONMENT != "development":
                return False
            if "invalid" in trans_sig.lower() or trans_sig == "TEST-INVALID-SIG":
                return False
            return True

        try:
            token = self._get_access_token()
            verify_url = f"{self.base_url}/v1/notifications/verify-webhook-signature"
            req_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            verification_payload = {
                "auth_algo": auth_algo,
                "cert_url": cert_url,
                "transmission_id": trans_id,
                "transmission_sig": trans_sig,
                "transmission_time": trans_time,
                "webhook_id": self.webhook_id,
                "webhook_event": json.loads(raw_body),
            }

            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(verify_url, headers=req_headers, json=verification_payload)

            if res.status_code == 200:
                data = res.json()
                return data.get("verification_status") == "SUCCESS"
            return False
        except Exception:
            return False


mock_provider_instance = MockPaymentProviderAdapter()
decoy_provider_instance = DecoyHoneyAdapter()
paypal_sandbox_provider_instance = PayPalSandboxAdapter()


def get_payment_provider() -> IPaymentProviderAdapter:
    if settings.PAYMENT_PROVIDER == "paypal_sandbox":
        return paypal_sandbox_provider_instance
    return mock_provider_instance


def get_decoy_provider() -> DecoyHoneyAdapter:
    return decoy_provider_instance
