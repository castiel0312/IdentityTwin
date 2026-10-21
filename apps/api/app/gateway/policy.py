from datetime import datetime, timezone

from app.core.config import settings
from app.gateway.routing import GatewayRoutingDecision
from app.risk.schemas import RiskEvaluationResult
from app.schemas.payouts import GatewayAction, PayoutRequest, RoutingDestination
from app.schemas.sessions import TrustLevel


class TrustGatewayPolicy:
    """
    Centralized Trust Gateway Routing Policy.

    Every protected transaction in IdentityTwin MUST be evaluated by this policy.
    No client request, frontend code, or external payload may override this logic.
    """

    def __init__(self, provider_mode: str = "mock"):
        self.provider_mode = provider_mode

    def evaluate(
        self,
        risk_result: RiskEvaluationResult,
        payout_request: PayoutRequest | None = None,
    ) -> GatewayRoutingDecision:
        level = risk_result.evaluated_trust_level
        reasons = list(risk_result.reason_codes)
        now = datetime.now(timezone.utc)

        # 1. ISOLATED (Level 3): Highest severity. Reject protected actions and deny further sensitive operations.
        if (
            level == TrustLevel.ISOLATED
            or risk_result.risk_score >= settings.RISK_THRESHOLD_ISOLATED
        ):
            reasons.append("POLICY_ENFORCED_SESSION_ISOLATION")
            return GatewayRoutingDecision(
                decision_id=risk_result.decision_id,
                session_id=risk_result.session_id,
                risk_score=risk_result.risk_score,
                trust_level=TrustLevel.ISOLATED,
                action=GatewayAction.BLOCK,
                routing_destination=RoutingDestination.ISOLATED_BLOCK,
                reason_codes=reasons,
                timestamp=now,
            )

        # 2. DECOY (Level 2): Route only supported honey-workspace interactions to synthetic handler.
        # CRITICAL: Never forward a payout to PayPal or real payment networks.
        if level == TrustLevel.DECOY or risk_result.risk_score >= settings.RISK_THRESHOLD_DECOY:
            reasons.append("POLICY_ENFORCED_DECOY_HONEYPOT_ROUTING")
            return GatewayRoutingDecision(
                decision_id=risk_result.decision_id,
                session_id=risk_result.session_id,
                risk_score=risk_result.risk_score,
                trust_level=TrustLevel.DECOY,
                action=GatewayAction.DECOY_FORWARD,
                routing_destination=RoutingDestination.DECOY_HONEY,
                reason_codes=reasons,
                timestamp=now,
            )

        # 3. RESTRICTED (Level 1): Enforce payout limits and required step-up verification.
        if (
            level == TrustLevel.RESTRICTED
            or risk_result.risk_score >= settings.RISK_THRESHOLD_RESTRICTED
        ):
            # Enforce reduced payout limit
            if payout_request and payout_request.amount > settings.RESTRICTED_PAYOUT_LIMIT:
                reasons.append("RESTRICTED_PAYOUT_LIMIT_EXCEEDED")
                return GatewayRoutingDecision(
                    decision_id=risk_result.decision_id,
                    session_id=risk_result.session_id,
                    risk_score=risk_result.risk_score,
                    trust_level=TrustLevel.RESTRICTED,
                    action=GatewayAction.REQUIRE_STEP_UP,
                    routing_destination=RoutingDestination.RESTRICTED_REJECT,
                    reason_codes=reasons,
                    timestamp=now,
                )

            # Step-up verification challenge
            if payout_request and payout_request.step_up_token in (
                "valid-step-up-token",
                "step_up_mfa_verified",
            ):
                reasons.append("RESTRICTED_STEP_UP_VERIFIED_PAYOUT_PERMITTED")
                destination = (
                    RoutingDestination.PROVIDER_PAYPAL
                    if self.provider_mode == "paypal_sandbox"
                    else RoutingDestination.PROVIDER_MOCK
                )
                return GatewayRoutingDecision(
                    decision_id=risk_result.decision_id,
                    session_id=risk_result.session_id,
                    risk_score=risk_result.risk_score,
                    trust_level=TrustLevel.RESTRICTED,
                    action=GatewayAction.ALLOW,
                    routing_destination=destination,
                    reason_codes=reasons,
                    timestamp=now,
                )

            # Default rejection without verified step-up token
            reasons.append("POLICY_ENFORCED_STEP_UP_CHALLENGE_REQUIRED")
            return GatewayRoutingDecision(
                decision_id=risk_result.decision_id,
                session_id=risk_result.session_id,
                risk_score=risk_result.risk_score,
                trust_level=TrustLevel.RESTRICTED,
                action=GatewayAction.REQUIRE_STEP_UP,
                routing_destination=RoutingDestination.RESTRICTED_REJECT,
                reason_codes=reasons,
                timestamp=now,
            )

        # 4. NORMAL (Level 0): Allow eligible action to proceed to the configured payment provider adapter.
        reasons.append("POLICY_NORMAL_EXECUTION_PERMITTED")
        destination = (
            RoutingDestination.PROVIDER_PAYPAL
            if self.provider_mode == "paypal_sandbox"
            else RoutingDestination.PROVIDER_MOCK
        )
        return GatewayRoutingDecision(
            decision_id=risk_result.decision_id,
            session_id=risk_result.session_id,
            risk_score=risk_result.risk_score,
            trust_level=TrustLevel.NORMAL,
            action=GatewayAction.ALLOW,
            routing_destination=destination,
            reason_codes=reasons,
            timestamp=now,
        )


default_policy = TrustGatewayPolicy(provider_mode=settings.PAYMENT_PROVIDER)


def get_gateway_policy() -> TrustGatewayPolicy:
    return default_policy
