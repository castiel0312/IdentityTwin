import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, Field

from app.core.config import (
    ALLOWED_PAYMENT_PROVIDERS,
    PAYMENT_PROVIDER_MOCK,
    PAYMENT_PROVIDER_PAYPAL_SANDBOX,
    settings,
    validate_paypal_base_url,
)
from app.core.exceptions import (
    AuthenticationRequiredException,
    IdentityTwinException,
    PaymentProviderException,
    ProviderRateLimitException,
    ProviderTimeoutException,
)
from app.schemas.payouts import PayoutRequest

# Canonical provider identities persisted on PayoutRequestRecord.provider_name.
# Each adapter declares its own identity on the ProviderPayoutResult it returns;
# the gateway persists that value verbatim so a payout record always names the
# adapter that actually executed it.
PROVIDER_NAME_NONE = "none"
PROVIDER_NAME_UNKNOWN = "unknown_provider"

# Must stay in sync with PayoutRequestRecord.provider_name (String(32)).
PROVIDER_NAME_MAX_LENGTH = 32

# PayPal rejects PayPal-Request-Id values longer than 38 characters with
# INVALID_PARAMETER_VALUE. Gateway idempotency keys are allowed to be longer
# (PayoutRequest.idempotency_key is String(128)), so over-long keys are mapped
# to a deterministic digest before they are sent to PayPal.
PAYPAL_REQUEST_ID_MAX_LENGTH = 38

# PayPal's own webhook signature verification endpoint. The host is selected by
# PAYPAL_BASE_URL; the path is identical for sandbox and production.
PAYPAL_WEBHOOK_VERIFY_PATH = "/v1/notifications/verify-webhook-signature"


def build_paypal_request_id(idempotency_key: str) -> str:
    """
    Build the PayPal-Request-Id header value for a payout request.

    The mapping is deterministic: the same gateway idempotency key always
    produces the same PayPal-Request-Id, which preserves provider level
    idempotency (PayPal replays the original response for a repeated request
    id) while never exceeding PayPal's 38 character limit.
    """
    key = (idempotency_key or "").strip()
    if not key:
        return uuid.uuid4().hex
    if len(key) <= PAYPAL_REQUEST_ID_MAX_LENGTH:
        return key
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:PAYPAL_REQUEST_ID_MAX_LENGTH]


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


def resolve_provider_name(result: ProviderPayoutResult) -> str:
    """
    Resolve the authoritative provider identity of an executed payout.

    The identity is taken from the adapter result so the persisted
    `provider_name` reflects the adapter that actually executed the payout
    (mock adapter, PayPal Sandbox, honey decoy, ...) instead of a hardcoded
    label that misattributes the transaction.

    A blank identity degrades to PROVIDER_NAME_UNKNOWN rather than
    PROVIDER_NAME_NONE, because a provider *did* execute: claiming that none
    did would be a false provenance statement.
    """
    name = (result.provider_name or "").strip()
    if not name:
        return PROVIDER_NAME_UNKNOWN
    return name[:PROVIDER_NAME_MAX_LENGTH]


def build_provider_payload(result: ProviderPayoutResult) -> dict[str, Any]:
    """
    Build the persisted provider payload for an executed payout.

    The adapter details are preserved as-is and enriched with the full provider
    provenance (untruncated identity and environment) so the audit trail keeps
    the exact provider identity even if it had to be truncated for the column.
    """
    return {
        **result.details,
        "provider_name": result.provider_name,
        "provider_environment": result.environment,
    }


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
        """
        The mock adapter CANNOT verify a PayPal transmission signature.

        This adapter used to accept any signature that merely "looked
        plausible" (anything that did not literally contain the word
        "invalid"). That was an unauthenticated write path: anyone able to
        reach the receiver could forge a payout reconciliation event.

        Verification is fail-closed here: the mock adapter never accepts a
        webhook. Only a real PayPal verification performed by
        PayPalSandboxAdapter (POST /v1/notifications/verify-webhook-signature)
        can accept one.
        """
        return False


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


def _uses_real_network(transport: httpx.BaseTransport | None) -> bool:
    """
    True when the adapter would really send bytes over the network.

    ``None`` selects httpx's default transport, and the two concrete HTTP
    transports dial out too. Test doubles (MockTransport, ASGITransport, ...)
    do not, so only those may be paired with a non-Sandbox base URL.
    """
    if transport is None:
        return True
    return isinstance(transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport))


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
        transport: httpx.BaseTransport | None = None,
    ):
        # `is not None` (and not a truthiness check) so that an explicitly
        # supplied empty credential means "not configured" instead of silently
        # falling back to the ambient environment credentials.
        self.client_id = client_id if client_id is not None else settings.PAYPAL_CLIENT_ID
        self.client_secret = (
            client_secret if client_secret is not None else settings.PAYPAL_CLIENT_SECRET
        )
        # Defense in depth: the ambient setting is already validated when
        # Settings is constructed at startup, but an injected base URL is only
        # allowed to bypass the Sandbox allowlist when a non-network transport
        # is supplied (the test seam). A real HTTP transport can reach PayPal,
        # so a non-Sandbox host must be impossible in that case.
        if base_url is not None and not _uses_real_network(transport):
            self.base_url = base_url.strip().rstrip("/")
        else:
            self.base_url = validate_paypal_base_url(
                base_url if base_url is not None else settings.PAYPAL_BASE_URL
            )
        self.timeout = timeout if timeout is not None else settings.PAYPAL_REQUEST_TIMEOUT
        self.webhook_id = webhook_id if webhook_id is not None else settings.PAYPAL_WEBHOOK_ID
        # Optional transport seam: production uses the default httpx transport,
        # automated tests inject httpx.MockTransport so no request can leave
        # the process.
        self.transport = transport
        self._token_cache: tuple[str, float] | None = None  # (token, expires_at_epoch)

    @staticmethod
    def _parse_json_object(res: httpx.Response, error_code: str) -> dict[str, Any]:
        """
        Parse a provider response body into a JSON object.

        A provider that answers with a non-JSON or non-object body is a
        provider contract violation, not an application error: it is surfaced
        as a PaymentProviderException instead of an unhandled decoding error.
        """
        try:
            payload = res.json()
        except ValueError:
            raise PaymentProviderException(
                message="PayPal Sandbox returned a non-JSON response body.",
                code=error_code,
                details={"status_code": res.status_code},
            ) from None
        if not isinstance(payload, dict):
            raise PaymentProviderException(
                message="PayPal Sandbox returned a non-object JSON response body.",
                code=error_code,
                details={"status_code": res.status_code},
            )
        return payload

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
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
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
        elif res.status_code == 429:
            raise ProviderRateLimitException(
                message="PayPal Sandbox rate limit exceeded while obtaining an access token.",
                code="PAYPAL_RATE_LIMIT",
            )
        elif res.status_code != 200:
            raise PaymentProviderException(
                message=f"PayPal OAuth token endpoint returned unexpected HTTP status {res.status_code}.",
                code="PAYPAL_OAUTH_ERROR",
            )

        try:
            token_data = res.json()
        except ValueError:
            raise PaymentProviderException(
                message="PayPal OAuth token endpoint returned a non-JSON response body.",
                code="PAYPAL_OAUTH_INVALID_PAYLOAD",
            ) from None
        if not isinstance(token_data, dict):
            raise PaymentProviderException(
                message="PayPal OAuth token endpoint returned a non-object JSON response body.",
                code="PAYPAL_OAUTH_INVALID_PAYLOAD",
            )

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
            "PayPal-Request-Id": build_paypal_request_id(request.idempotency_key),
        }

        now_executed = datetime.now(timezone.utc)

        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
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

        res_data = self._parse_json_object(res, "PAYPAL_INVALID_RESPONSE")
        batch_header = res_data.get("batch_header") or {}
        if not isinstance(batch_header, dict):
            batch_header = {}
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
        Verifies a PayPal webhook signature via POST /v1/notifications/verify-webhook-signature.

        FAIL-CLOSED BY CONSTRUCTION. A webhook is accepted ONLY when PayPal
        itself answers `verification_status == "SUCCESS"` for the configured
        webhook id. Every other outcome is rejected:

        - any missing PayPal transmission header,
        - a missing webhook id or missing credentials (no request is sent at
          all, because an unconfigured adapter cannot validate anything),
        - a body that is not a JSON object,
        - a provider error status, a malformed or non-object provider body,
        - a timeout, a network failure or an unusable request URL.

        There is deliberately NO development fallback that accepts a signature
        on plausibility: an unverifiable webhook is not a webhook. The
        credentials, the access token, the transmission signature and the
        payload are never logged.
        """
        normalized = {k.lower(): v for k, v in headers.items()}
        auth_algo = normalized.get("paypal-auth-algo")
        cert_url = normalized.get("paypal-cert-url")
        trans_id = normalized.get("paypal-transmission-id")
        trans_sig = normalized.get("paypal-transmission-sig")
        trans_time = normalized.get("paypal-transmission-time")

        if not all([auth_algo, cert_url, trans_id, trans_sig, trans_time]):
            return False

        # Fail closed when the adapter is not configured for webhook
        # verification. Missing configuration means the signature cannot be
        # validated, so the provider is never contacted.
        if not self.webhook_id or not self.client_id or not self.client_secret:
            return False

        # PayPal verifies the signature against the exact event bytes, so the
        # event must be a JSON object; anything else can never be verified.
        try:
            webhook_event = json.loads(raw_body)
        except ValueError:
            return False
        if not isinstance(webhook_event, dict):
            return False

        try:
            token = self._get_access_token()
        except IdentityTwinException:
            # Missing/invalid credentials, rate limiting, timeouts and provider
            # errors are all verification failures, never acceptances.
            return False

        verify_url = f"{self.base_url}{PAYPAL_WEBHOOK_VERIFY_PATH}"
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
            "webhook_event": webhook_event,
        }

        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                res = client.post(verify_url, headers=req_headers, json=verification_payload)
        except (httpx.HTTPError, httpx.InvalidURL):
            # Timeouts and network failures are rejected, never accepted.
            return False

        if res.status_code != 200:
            return False

        try:
            data = res.json()
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        return data.get("verification_status") == "SUCCESS"


mock_provider_instance = MockPaymentProviderAdapter()
decoy_provider_instance = DecoyHoneyAdapter()
paypal_sandbox_provider_instance = PayPalSandboxAdapter()


def get_configured_payment_provider_name() -> str:
    """
    Resolve the current, normalized payment provider selection.

    This is the single source of truth shared by the routing policy and the
    adapter factory: both must derive from the same value so the declared
    routing destination can never disagree with the adapter that actually
    executes a payout. Unknown values fail closed and are never mapped to the
    mock provider.
    """
    provider = (settings.PAYMENT_PROVIDER or "").strip().lower()
    if provider not in ALLOWED_PAYMENT_PROVIDERS:
        raise IdentityTwinException(
            message=(
                f"Unknown PAYMENT_PROVIDER '{settings.PAYMENT_PROVIDER}'. "
                "Allowed values: 'mock', 'paypal_sandbox'."
            ),
            code="PAYMENT_PROVIDER_UNKNOWN",
            status_code=500,
        )
    return provider


def get_payment_provider(provider_name: str | None = None) -> IPaymentProviderAdapter:
    # The gateway passes the provider name from the same policy decision that
    # produced the routing destination. Direct callers still get the current
    # configured value. In both cases the value is normalized and validated;
    # an unrecognized value never silently selects a different adapter
    # (especially not the mock one, which would pretend a payout executed).
    provider = (
        get_configured_payment_provider_name()
        if provider_name is None
        else provider_name.strip().lower()
    )
    if provider == PAYMENT_PROVIDER_PAYPAL_SANDBOX:
        return paypal_sandbox_provider_instance
    if provider == PAYMENT_PROVIDER_MOCK:
        return mock_provider_instance
    raise IdentityTwinException(
        message=(
            f"Unknown PAYMENT_PROVIDER '{provider}'. Allowed values: 'mock', 'paypal_sandbox'."
        ),
        code="PAYMENT_PROVIDER_UNKNOWN",
        status_code=500,
    )


def get_decoy_provider() -> DecoyHoneyAdapter:
    return decoy_provider_instance
