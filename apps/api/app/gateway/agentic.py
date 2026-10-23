"""
Internal agentic commerce adapter and service (Person 3).

This module implements the INTERNAL adapter contract between an AI agent (or
the merchant application embedding one) and the IdentityTwin Trust Gateway.

There is no third-party agentic payment specification implemented here. The
contract is documented in `docs/agentic-commerce.md` and consists of:

    IAgenticCommerceAdapter
        authorize(...)  -> AgentAuthorizationDecision
        normalize(...)  -> PayoutRequest

The adapter is the only component that understands agent shaped input. It
resolves the acting agent and its delegation from the server side registry,
verifies that the delegation covers this principal, this session, this scope
and this amount, and then normalizes the request into the canonical
`PayoutRequest` that the Trust Gateway already understands.

INVARIANTS enforced here:

* No payment provider is ever contacted from this module. The adapter
  normalizes into `PayoutRequest` and delegates to `TrustGatewayService`,
  which owns every routing, risk and provider decision.
* Merchant identity is never taken from the request body: it always comes
  from the authenticated principal.
* Agent identity is never taken from the request body beyond an opaque
  `agent_id` reference: display name, type, scopes and limits are always
  resolved from the registry.
* The caller supplied idempotency key is preserved verbatim so the Trust
  Gateway deduplicates agent retries exactly like human initiated payouts.
* The risk engine (Person 2) is never modified or bypassed: agent requests
  are evaluated by the same server side risk engine as every other payout.
"""

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.core.exceptions import (
    DuplicateRequestException,
    InsufficientPermissionsException,
)
from app.core.security import AuthenticatedPrincipal
from app.db.repositories.agent_repo import AgentRepository
from app.db.repositories.payout_repo import PayoutRepository
from app.gateway.service import TrustGatewayService, get_gateway_service
from app.models.agent import (
    AgentAuthorizationGrant,
    AgenticCommerceAudit,
    AgentRegistration,
    AgentStatus,
)
from app.schemas.agentic import (
    AgentAuthorizationContext,
    AgentAuthorizationDecision,
    AgenticCommerceRequest,
    AgenticCommerceResponse,
    AgentIdentity,
    AgentScope,
)
from app.schemas.payouts import PayoutRequest, PayoutResponse


@runtime_checkable
class IAgenticCommerceAdapter(Protocol):
    """
    Internal adapter interface for agent initiated commerce.

    The interface is intentionally small and transport agnostic: it takes a
    validated `AgenticCommerceRequest` plus the authenticated principal and
    returns either an authorization decision or a canonical `PayoutRequest`.
    Implementations must be side effect free until the Trust Gateway accepts
    the normalized request.
    """

    def authorize(
        self,
        db: Session,
        request: AgenticCommerceRequest,
        principal: AuthenticatedPrincipal,
    ) -> AgentAuthorizationDecision: ...

    def normalize(
        self,
        request: AgenticCommerceRequest,
        principal: AuthenticatedPrincipal,
        decision: AgentAuthorizationDecision,
    ) -> PayoutRequest: ...


class AgenticCommerceAdapter:
    """
    Default implementation of the internal agentic adapter contract.

    The adapter resolves the agent registry and the delegation grants, and it
    never mutates payment state: normalization produces a `PayoutRequest` and
    the Trust Gateway performs the actual execution.
    """

    def __init__(self, required_scope: AgentScope = AgentScope.PAYOUT_EXECUTE):
        self.required_scope = required_scope

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------
    def authorize(
        self,
        db: Session,
        request: AgenticCommerceRequest,
        principal: AuthenticatedPrincipal,
    ) -> AgentAuthorizationDecision:
        repo = AgentRepository(db)

        agent = repo.get_agent(request.agent_id)
        if agent is None:
            raise InsufficientPermissionsException(
                message="Agent is not registered.",
                code="AGENT_NOT_REGISTERED",
                details={"agent_id": str(request.agent_id)},
            )

        if agent.merchant_id != principal.merchant_id:
            raise InsufficientPermissionsException(
                message="Agent is registered to a different merchant.",
                code="AGENT_MERCHANT_MISMATCH",
                details={"agent_id": str(request.agent_id)},
            )

        if not agent.is_active or agent.status != AgentStatus.ACTIVE:
            raise InsufficientPermissionsException(
                message=f"Agent registration is '{agent.status}' and cannot act.",
                code="AGENT_NOT_ACTIVE",
                details={"agent_id": str(request.agent_id), "status": agent.status},
            )

        grant = repo.get_grant(request.authorization_grant_id)
        if grant is None:
            raise InsufficientPermissionsException(
                message="Authorization grant not found for this agent.",
                code="AGENT_AUTHORIZATION_MISSING",
                details={"authorization_grant_id": str(request.authorization_grant_id)},
            )

        if grant.agent_id != agent.agent_id:
            raise InsufficientPermissionsException(
                message="Authorization grant was not issued to this agent.",
                code="AGENT_AUTHORIZATION_AGENT_MISMATCH",
                details={"authorization_grant_id": str(grant.grant_id)},
            )

        if grant.merchant_id != principal.merchant_id:
            raise InsufficientPermissionsException(
                message="Authorization grant belongs to a different merchant.",
                code="AGENT_AUTHORIZATION_MERCHANT_MISMATCH",
                details={"authorization_grant_id": str(grant.grant_id)},
            )

        if grant.user_id != principal.user_id:
            raise InsufficientPermissionsException(
                message="Authorization grant was issued to a different merchant user.",
                code="AGENT_AUTHORIZATION_PRINCIPAL_MISMATCH",
                details={"authorization_grant_id": str(grant.grant_id)},
            )

        if grant.revoked_at is not None:
            raise InsufficientPermissionsException(
                message="Authorization grant has been revoked.",
                code="AGENT_AUTHORIZATION_REVOKED",
                details={"authorization_grant_id": str(grant.grant_id)},
            )

        # A consumed single-use grant authorizes nothing, except the replay of
        # the very request that consumed it: the caller must still be able to
        # retrieve the cached outcome of its own idempotent retry.
        if grant.consumed_at is not None and not self._has_replayable_result(
            db, principal, request, agent
        ):
            raise InsufficientPermissionsException(
                message="Authorization grant has already been used.",
                code="AGENT_AUTHORIZATION_CONSUMED",
                details={"authorization_grant_id": str(grant.grant_id)},
            )

        if self._is_expired(grant):
            raise InsufficientPermissionsException(
                message="Authorization grant has expired.",
                code="AGENT_AUTHORIZATION_EXPIRED",
                details={"authorization_grant_id": str(grant.grant_id)},
            )

        if grant.session_id is not None and grant.session_id != request.session_id:
            raise InsufficientPermissionsException(
                message="Authorization grant is bound to a different session.",
                code="AGENT_AUTHORIZATION_SESSION_MISMATCH",
                details={"authorization_grant_id": str(grant.grant_id)},
            )

        scope = self.required_scope.value
        if scope not in list(grant.scopes or []) or scope not in list(agent.scopes or []):
            raise InsufficientPermissionsException(
                message=f"Agent is not authorized for scope '{scope}'.",
                code="AGENT_SCOPE_NOT_GRANTED",
                details={"required_scope": scope},
            )

        self._enforce_amount_limits(request, agent, grant)

        self._assert_idempotency_context(db, request, principal, agent)

        authorization = AgentAuthorizationContext(
            grant_id=grant.grant_id,
            agent_id=agent.agent_id,
            merchant_id=principal.merchant_id,
            delegated_by_user_id=grant.delegated_by_user_id or grant.user_id,
            session_id=grant.session_id,
            scopes=list(grant.scopes or []),
            max_amount=grant.max_amount,
            issued_at=grant.issued_at,
            expires_at=grant.expires_at,
        )
        identity = AgentIdentity(
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            agent_type=agent.agent_type,
            vendor=agent.vendor,
            scopes=list(agent.scopes or []),
            status=agent.status,
        )
        return AgentAuthorizationDecision(agent=identity, authorization=authorization)

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------
    def normalize(
        self,
        request: AgenticCommerceRequest,
        principal: AuthenticatedPrincipal,
        decision: AgentAuthorizationDecision,
    ) -> PayoutRequest:
        """
        Normalize an agent request into the canonical gateway request.

        The merchant identity is implicit: `PayoutRequest` carries no merchant
        field, so the Trust Gateway always resolves it from the authenticated
        principal. The session identity is preserved from the authorized
        request, and the idempotency key is preserved verbatim.
        """
        if decision.authorization.merchant_id != principal.merchant_id:
            # Defence in depth: a decision must never be applied to another
            # merchant than the one it was authorized for.
            raise InsufficientPermissionsException(
                message="Authorization decision does not belong to the authenticated merchant.",
                code="AGENT_AUTHORIZATION_MERCHANT_MISMATCH",
                details={"agent_id": str(decision.agent.agent_id)},
            )

        session_id = request.session_id
        if decision.authorization.session_id is not None:
            session_id = decision.authorization.session_id

        return PayoutRequest(
            session_id=session_id,
            recipient_email=request.recipient_email,
            amount=request.amount,
            currency=request.currency,
            reference_note=self._provenance_note(request, decision),
            idempotency_key=request.idempotency_key,
            step_up_token=request.step_up_token,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _provenance_note(
        self, request: AgenticCommerceRequest, decision: AgentAuthorizationDecision
    ) -> str | None:
        """
        Attach a bounded agent provenance marker to the business reference.

        The marker lets the evidence pipeline attribute an outbound payment to
        the acting agent even when only payout records are inspected.
        """
        marker = f"[agent:{decision.agent.agent_id}]"
        note = request.reference_note
        if not note:
            return marker
        return f"{note} {marker}"[:255]

    @staticmethod
    def _is_expired(grant: AgentAuthorizationGrant) -> bool:
        expires_at = grant.expires_at
        if expires_at is None:
            return True
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)

    @staticmethod
    def _enforce_amount_limits(
        request: AgenticCommerceRequest,
        agent: AgentRegistration,
        grant: AgentAuthorizationGrant,
    ) -> None:
        limits = [
            limit for limit in (grant.max_amount, agent.max_payout_amount) if limit is not None
        ]
        if not limits:
            return
        effective_limit = min(limits)
        if request.amount > effective_limit:
            raise InsufficientPermissionsException(
                message="Requested amount exceeds the agent authorization limit.",
                code="AGENT_AMOUNT_LIMIT_EXCEEDED",
                details={
                    "requested_amount": request.amount,
                    "authorized_limit": effective_limit,
                },
            )

    @staticmethod
    def _assert_idempotency_context(
        db: Session,
        request: AgenticCommerceRequest,
        principal: AuthenticatedPrincipal,
        agent: AgentRegistration,
    ) -> None:
        """
        Refuse to reuse an idempotency key that belongs to another context.

        The Trust Gateway namespaces idempotency keys by merchant. An agent
        must never be able to replay the key of a direct human payout (or of
        another agent) and inherit its cached result, so the binding is
        verified before the request reaches the gateway.
        """
        existing = PayoutRepository(db).get_by_idempotency_key(
            principal.merchant_id, request.idempotency_key
        )
        if existing is None:
            return

        prior_audit = AgentRepository(db).latest_audit_for_key(
            principal.merchant_id, request.idempotency_key
        )
        if prior_audit is None or prior_audit.agent_id != agent.agent_id:
            raise DuplicateRequestException(
                message=(
                    "Idempotency key is already bound to a different execution context "
                    "and cannot be reused by an agent."
                ),
                code="AGENT_IDEMPOTENCY_KEY_CONFLICT",
                details={"idempotency_key": request.idempotency_key},
            )

    @staticmethod
    def _has_replayable_result(
        db: Session,
        principal: AuthenticatedPrincipal,
        request: AgenticCommerceRequest,
        agent: AgentRegistration,
    ) -> bool:
        prior_audit = AgentRepository(db).latest_audit_for_key(
            principal.merchant_id, request.idempotency_key
        )
        if prior_audit is None or prior_audit.agent_id != agent.agent_id:
            return False
        return prior_audit.status in ("completed", "decoy_completed", "blocked")


class AgenticCommerceService:
    """
    Orchestrates agent initiated commerce through the Trust Gateway.

    The service is the only entry point used by the HTTP layer. It resolves
    authorization, normalizes the request and delegates execution to the
    Trust Gateway; it never performs a provider call itself.
    """

    def __init__(
        self,
        adapter: IAgenticCommerceAdapter,
        gateway_service: TrustGatewayService,
    ):
        self.adapter = adapter
        self.gateway_service = gateway_service

    def submit(
        self,
        db: Session,
        request: AgenticCommerceRequest,
        principal: AuthenticatedPrincipal,
    ) -> AgenticCommerceResponse:
        decision = self.adapter.authorize(db=db, request=request, principal=principal)
        payout_request = self.adapter.normalize(
            request=request, principal=principal, decision=decision
        )

        try:
            payout_response = self.gateway_service.execute_payout(
                db=db, request=payout_request, principal=principal
            )
        except Exception as exc:
            self._record_audit(
                db=db,
                request=request,
                principal=principal,
                decision=decision,
                status="failed",
                outcome=type(exc).__name__,
                payout_response=None,
            )
            raise

        self._record_audit(
            db=db,
            request=request,
            principal=principal,
            decision=decision,
            status=payout_response.status,
            outcome=(
                "duplicate_replay" if payout_response.is_duplicate else payout_response.action.value
            ),
            payout_response=payout_response,
        )

        return AgenticCommerceResponse(
            **payout_response.model_dump(),
            agent_id=decision.agent.agent_id,
            agent_display_name=decision.agent.display_name,
            agent_type=decision.agent.agent_type,
            authorization_grant_id=decision.authorization.grant_id,
            delegated_by_user_id=decision.authorization.delegated_by_user_id,
            agent_intent=request.agent_intent,
        )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def _record_audit(
        self,
        db: Session,
        request: AgenticCommerceRequest,
        principal: AuthenticatedPrincipal,
        decision: AgentAuthorizationDecision,
        status: str,
        outcome: str,
        payout_response: PayoutResponse | None,
    ) -> None:
        repo = AgentRepository(db)
        audit = AgenticCommerceAudit(
            agent_id=decision.agent.agent_id,
            grant_id=decision.authorization.grant_id,
            merchant_id=principal.merchant_id,
            user_id=principal.user_id,
            session_id=request.session_id,
            payout_id=payout_response.payout_id if payout_response else None,
            idempotency_key=request.idempotency_key,
            recipient_email=request.recipient_email,
            amount=request.amount,
            currency=request.currency,
            status=status,
            outcome=outcome,
            agent_context={
                **decision.authorization.as_audit_context(),
                "agent_display_name": decision.agent.display_name,
                "agent_type": decision.agent.agent_type,
                "agent_vendor": decision.agent.vendor,
                "agent_status": decision.agent.status,
                "agent_intent": request.agent_intent,
                "step_up_token_present": request.step_up_token is not None,
                "is_duplicate": bool(payout_response.is_duplicate) if payout_response else False,
            },
        )
        repo.record_audit(audit)


def create_agentic_commerce_service(
    adapter: IAgenticCommerceAdapter | None = None,
    gateway_service: TrustGatewayService | None = None,
) -> AgenticCommerceService:
    return AgenticCommerceService(
        adapter=adapter or AgenticCommerceAdapter(),
        gateway_service=gateway_service or get_gateway_service(),
    )


def get_agentic_commerce_service() -> AgenticCommerceService:
    return create_agentic_commerce_service()
