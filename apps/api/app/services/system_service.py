"""System context projection.

Configuration values are safe, non-secret facts (mode, thresholds, weights,
availability). Credentials are never projected.
"""


from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import AuthenticatedPrincipal
from app.gateway.provider import get_configured_payment_provider_name
from app.models.principal import Merchant
from app.risk.config import get_risk_config
from app.schemas.system import (
    AuthContextView,
    CapabilityView,
    MerchantView,
    PrincipalView,
    ProviderContextView,
    RiskContextView,
    RiskSignalWeight,
    SystemContextResponse,
    ThresholdView,
)

SIGNAL_DESCRIPTIONS = {
    "NEW_DEVICE": "Device fingerprint was not part of the identity's confirmed baseline.",
    "NEW_LOCATION": "Network origin bucket was not part of the confirmed location baseline.",
    "UNUSUAL_TIME": "Action occurred outside the identity's confirmed active hours.",
    "NEW_PAYEE": "Recipient was not previously observed for this identity.",
    "LARGE_PAYOUT": "Amount exceeded both the absolute and relative large-payout threshold.",
    "NEW_PAYEE_LARGE_PAYOUT": "A new payee was combined with a large payout.",
    "PAYEE_ADD_THEN_PAYOUT": "A payee was registered and paid inside the sequence window.",
    "CANARY_INTERACTION": "A uniquely tagged synthetic resource was accessed; forces isolation.",
}


def build_system_context(
    db: Session, principal: AuthenticatedPrincipal
) -> SystemContextResponse:
    config = get_risk_config()
    merchant = db.get(Merchant, principal.merchant_id)
    provider_mode = get_configured_payment_provider_name()
    environment = settings.ENVIRONMENT.lower()
    is_production = environment == "production"
    oidc_configured = False  # The backend returns 501 until a real verifier is wired.

    auth_mode = "oidc_unconfigured" if is_production else "development_dev_token"
    auth_limitations = [
        "Production OIDC/JWKS verification is not implemented by the backend (501).",
        "Development identity is derived from well-known bearer tokens and X-Dev-* headers.",
    ]
    if not is_production:
        auth_limitations.append(
            "Development credentials are rejected when ENVIRONMENT=production."
        )

    capabilities = [
        CapabilityView(
            id="payout_read",
            name="Payout ledger",
            available=True,
            detail="Server-projected payout, decision, provider and evidence state.",
        ),
        CapabilityView(
            id="payout_execute",
            name="Payout execution",
            available=True,
            detail="All execution is routed through the Trust Gateway.",
        ),
        CapabilityView(
            id="incident_actions",
            name="Incident approvals",
            available=True,
            detail="Approve, resolve and approve-revocation require the analyst role.",
        ),
        CapabilityView(
            id="evidence_verify",
            name="Whole-chain evidence verification",
            available=True,
            detail="Hash-chain and checkpoint consistency only; not an immutability proof.",
        ),
        CapabilityView(
            id="sse_events",
            name="Tenant-scoped domain event stream",
            available=True,
            detail=(
                "Authenticated SSE at /v1/events/stream with durable ordered replay "
                "for 30 days."
            ),
        ),
        CapabilityView(
            id="oidc",
            name="OIDC authentication",
            available=oidc_configured,
            detail="Backend returns 501 for the production OIDC hook.",
        ),
        CapabilityView(
            id="legacy_stream",
            name="Legacy /v1/stream",
            available=False,
            detail="Backend stub returns 501; use /v1/events/stream instead.",
        ),
        CapabilityView(
            id="signature_approval",
            name="Evidence signature approval",
            available=False,
            detail="Backend stub returns 501; seals are verified via the hash chain.",
        ),
        CapabilityView(
            id="grant_management",
            name="Agent grant editing",
            available=False,
            detail="The backend exposes a read-only registry; grants are seeded administratively.",
        ),
    ]

    weights = [
        RiskSignalWeight(
            name=name,
            weight=float(getattr(config, attr)),
            description=SIGNAL_DESCRIPTIONS[name],
        )
        for name, attr in (
            ("NEW_DEVICE", "weight_new_device"),
            ("NEW_LOCATION", "weight_new_location"),
            ("UNUSUAL_TIME", "weight_unusual_time"),
            ("NEW_PAYEE", "weight_new_payee"),
            ("LARGE_PAYOUT", "weight_large_payout"),
            ("NEW_PAYEE_LARGE_PAYOUT", "weight_new_payee_large_payout"),
            ("PAYEE_ADD_THEN_PAYOUT", "weight_payee_add_then_payout"),
            ("CANARY_INTERACTION", "weight_canary_interaction"),
        )
    ]

    return SystemContextResponse(
        principal=PrincipalView(
            user_id=principal.user_id,
            merchant_id=principal.merchant_id,
            role=principal.role.value,
            username=principal.username,
            auth_method=principal.auth_method,
        ),
        merchant=(
            MerchantView(
                merchant_id=merchant.merchant_id,
                name=merchant.name,
                slug=merchant.slug,
                is_active=merchant.is_active,
            )
            if merchant
            else None
        ),
        environment=settings.ENVIRONMENT,
        auth=AuthContextView(
            mode=auth_mode,
            development_only=not is_production,
            oidc_configured=oidc_configured,
            limitations=auth_limitations,
        ),
        provider=ProviderContextView(
            mode=provider_mode,
            sandbox_only=True,
            webhook_verification_configured=bool(
                provider_mode == "paypal_sandbox" and settings.PAYPAL_WEBHOOK_ID.strip()
            ),
            notes=[
                "PAYPAL_BASE_URL is allowlisted to https://api-m.sandbox.paypal.com.",
                "Inbound PayPal webhooks are verified fail-closed by the provider adapter.",
                (
                    "Mock provider is active: no external payment network is contacted."
                    if provider_mode == "mock"
                    else "PayPal Sandbox adapter is active."
                ),
            ],
        ),
        thresholds=ThresholdView(
            restricted=config.threshold_restricted,
            decoy=config.threshold_decoy,
            isolated=config.threshold_isolated,
            restricted_payout_limit=settings.RESTRICTED_PAYOUT_LIMIT,
            baseline_score=config.baseline_score,
        ),
        risk=RiskContextView(
            weights=weights,
            sequence_window_seconds=config.sequence_window_seconds,
            min_samples=config.min_samples,
            provisional_factor=config.provisional_factor,
            decay_points_per_event=config.decay_points_per_event,
            default_timezone=config.default_timezone,
            protected_actions=sorted(config.protected_actions),
        ),
        capabilities=capabilities,
    )
