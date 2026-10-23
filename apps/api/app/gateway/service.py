import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import (
    DuplicateRequestException,
    EntityNotFoundException,
    OwnershipMismatchException,
    PaymentProviderException,
    PolicyViolationException,
    ProviderTimeoutException,
)
from app.core.security import AuthenticatedPrincipal
from app.db.repositories.idempotency_repo import IdempotencyRepository
from app.db.repositories.payout_repo import PayoutRepository
from app.db.repositories.session_repo import SessionRepository
from app.gateway.policy import TrustGatewayPolicy, get_gateway_policy
from app.gateway.provider import (
    PROVIDER_NAME_NONE,
    DecoyHoneyAdapter,
    IPaymentProviderAdapter,
    build_provider_payload,
    get_decoy_provider,
    get_payment_provider,
    resolve_provider_name,
)
from app.models.idempotency import IdempotencyRecord
from app.models.payout import PayoutRequestRecord
from app.models.risk import RiskDecisionRecord
from app.risk.schemas import RiskEvaluationRequest
from app.risk.service import IRiskEngineService, get_risk_engine
from app.schemas.payouts import GatewayAction, PayoutRequest, PayoutResponse
from app.schemas.sessions import SessionStatus


class TrustGatewayService:
    """
    Centralized Trust Gateway Service for IdentityTwin.

    All payout executions and high-risk operations MUST pass through this service.
    No route handler may invoke payment provider adapters directly.
    """

    def __init__(
        self,
        policy: TrustGatewayPolicy,
        risk_engine: IRiskEngineService,
        provider_adapter: IPaymentProviderAdapter,
        decoy_adapter: DecoyHoneyAdapter,
    ):
        self.policy = policy
        self.risk_engine = risk_engine
        self.provider_adapter = provider_adapter
        self.decoy_adapter = decoy_adapter

    def execute_payout(
        self,
        db: Session,
        request: PayoutRequest,
        principal: AuthenticatedPrincipal,
    ) -> PayoutResponse:
        session_repo = SessionRepository(db)
        payout_repo = PayoutRepository(db)
        idempotency_repo = IdempotencyRepository(db)

        # 1 & 2. Validate session exists, is active, and belongs to caller with row-level lock
        session = session_repo.get_by_id(request.session_id, for_update=True)
        if not session:
            raise EntityNotFoundException(
                message=f"Session '{request.session_id}' not found.",
                code="SESSION_NOT_FOUND",
            )

        if session.merchant_id != principal.merchant_id or session.user_id != principal.user_id:
            raise OwnershipMismatchException(
                message="Session does not belong to the authenticated principal.",
                code="SESSION_OWNERSHIP_MISMATCH",
            )

        if session.status != SessionStatus.ACTIVE.value:
            raise PolicyViolationException(
                message=f"Session is in '{session.status}' state and cannot perform payouts.",
                code="INACTIVE_SESSION",
            )

        # 3 & 4. Idempotency and duplicate check
        req_hash = hashlib.sha256(
            f"{request.recipient_email}:{request.amount}:{request.currency}".encode()
        ).hexdigest()

        cached_rec = idempotency_repo.get_record(principal.merchant_id, request.idempotency_key)
        idem_record = None
        if cached_rec:
            # Prevent idempotency parameter tampering (key reuse with different amounts/recipients)
            if cached_rec.request_hash != req_hash:
                raise PolicyViolationException(
                    message="Idempotency key was previously used with different request parameters.",
                    code="IDEMPOTENCY_KEY_PAYLOAD_MISMATCH",
                )

            if cached_rec.status == "completed":
                payload = dict(cached_rec.response_payload)
                payload["is_duplicate"] = True
                return PayoutResponse(**payload)
            elif cached_rec.status in ("provider_executed", "needs_reconciliation"):
                # Provider was already executed previously! Re-execution is strictly denied.
                raise PolicyViolationException(
                    message=(
                        "Payout provider was previously executed for this idempotency key and requires "
                        "reconciliation. Provider execution will not be repeated."
                    ),
                    code="PAYOUT_ALREADY_EXECUTED_RECONCILIATION_REQUIRED",
                    details=cached_rec.response_payload,
                )
            elif cached_rec.status == "processing":
                raise DuplicateRequestException(
                    message="A request with this idempotency key is already processing.",
                    code="IDEMPOTENCY_IN_PROGRESS",
                )
            # status == "failed": the previous attempt failed before the provider
            # executed anything, so the key is safe to retry. The existing
            # record is reused instead of inserting a second row for the same
            # (merchant_id, idempotency_key) pair, which would violate the
            # unique idempotency index.
            idem_record = cached_rec

        # Record in-progress idempotency record
        now = datetime.now(timezone.utc)
        if idem_record is None:
            idem_record = IdempotencyRecord(
                idempotency_key=request.idempotency_key,
                merchant_id=principal.merchant_id,
                request_hash=req_hash,
                status="processing",
                expires_at=now + timedelta(hours=24),
            )
        else:
            idem_record.request_hash = req_hash
            idem_record.status = "processing"
            idem_record.response_code = None
            idem_record.response_payload = {}
            idem_record.expires_at = now + timedelta(hours=24)
        idempotency_repo.save_record(idem_record)

        try:
            # 5. Server-side risk evaluation
            risk_eval_req = RiskEvaluationRequest(
                session_id=session.session_id,
                merchant_id=principal.merchant_id,
                user_id=principal.user_id,
                action_type="payout",
                amount=request.amount,
                recipient=request.recipient_email,
                # Person 2 (additive): device and network evidence is inherited
                # from the authoritative session record when the payout request
                # itself does not carry it.
                device_id=session.device_fingerprint,
                ip_address=session.ip_address,
                occurred_at=now,
                event_id=uuid.uuid4(),
                event_type="payout.submit",
            )
            risk_result = self.risk_engine.evaluate(db, session, risk_eval_req)

            # Step-up verification check for restricted clearances
            step_up_verified = False
            step_up_challenge = None
            step_up_repo = None
            if request.step_up_token:
                try:
                    challenge_id = uuid.UUID(request.step_up_token)
                    from app.db.repositories.step_up_repo import StepUpRepository

                    step_up_repo = StepUpRepository(db)
                    challenge = step_up_repo.get_by_id(challenge_id)
                    if challenge:
                        exp = challenge.expires_at
                        if exp.tzinfo is None:
                            exp = exp.replace(tzinfo=timezone.utc)
                        if (
                            challenge.session_id == session.session_id
                            and challenge.merchant_id == principal.merchant_id
                            and challenge.verified_at is not None
                            and challenge.used_at is None
                            and exp > datetime.now(timezone.utc)
                        ):
                            step_up_verified = True
                            step_up_challenge = challenge
                except (ValueError, TypeError):
                    step_up_verified = False

            # 6. Apply centralized gateway routing policy
            routing_decision = self.policy.evaluate(
                risk_result, payout_request=request, step_up_verified=step_up_verified
            )

            # Persist RiskDecisionRecord for auditable evidence
            db_decision = RiskDecisionRecord(
                decision_id=routing_decision.decision_id,
                session_id=session.session_id,
                merchant_id=principal.merchant_id,
                risk_score=routing_decision.risk_score,
                trust_level=routing_decision.trust_level.value,
                action=routing_decision.action.value,
                routing_destination=routing_decision.routing_destination.value,
                reason_codes=routing_decision.reason_codes,
                risk_signals=risk_result.risk_signals,
                evaluated_at=routing_decision.timestamp,
            )
            payout_repo.save_decision(db_decision)

            # 7. Gateway routing execution
            # CRITICAL INVARIANT: Disallowed trust states (RESTRICTED, DECOY, ISOLATED) NEVER invoke provider adapter!
            payout_id = uuid.uuid4()
            provider_reference = None
            provider_payload = {}
            payout_status = "rejected"
            executed_at = None

            provider_invoked = False
            provider_result = None
            provider_reported_failure = False
            provider_name = PROVIDER_NAME_NONE

            if routing_decision.action == GatewayAction.ALLOW:
                # Consume single-use step-up challenge if used
                if step_up_challenge and step_up_repo:
                    step_up_repo.mark_used(step_up_challenge)

                # Legitimate transaction routed to payment provider adapter
                provider_invoked = True
                provider_result = self.provider_adapter.execute_payout(
                    request, principal.merchant_id
                )
                if not provider_result.success:
                    # The provider reported a definitive, unsuccessful
                    # execution: no funds were moved, so the idempotency key
                    # stays safe to retry. A payout must never be persisted as
                    # "completed" when the adapter reported a failure.
                    provider_reported_failure = True
                    raise PaymentProviderException(
                        message="Payment provider reported an unsuccessful payout execution.",
                        code="PROVIDER_EXECUTION_UNSUCCESSFUL",
                        details={
                            "provider_transaction_id": provider_result.provider_transaction_id,
                            "provider_name": provider_result.provider_name,
                        },
                    )
                provider_reference = provider_result.provider_transaction_id
                provider_name = resolve_provider_name(provider_result)
                provider_payload = build_provider_payload(provider_result)
                payout_status = "completed"
                executed_at = provider_result.executed_at
            elif routing_decision.action == GatewayAction.DECOY_FORWARD:
                # Routed to isolated synthetic honey environment
                decoy_result = self.decoy_adapter.execute_decoy(request, principal.merchant_id)
                provider_reference = decoy_result.provider_transaction_id
                provider_name = resolve_provider_name(decoy_result)
                provider_payload = build_provider_payload(decoy_result)
                payout_status = "decoy_completed"
                executed_at = decoy_result.executed_at
            elif routing_decision.action == GatewayAction.REQUIRE_STEP_UP:
                payout_status = "rejected"
                provider_payload = {"policy_rejection": "RESTRICTED_STEP_UP_CHALLENGE_REQUIRED"}
            elif routing_decision.action == GatewayAction.BLOCK:
                payout_status = "blocked"
                provider_payload = {"policy_rejection": "ISOLATED_SECURITY_BLOCK"}
                # Trigger centralized isolation and open security incident
                from app.gateway.isolation import isolate_session_and_open_incident

                isolate_session_and_open_incident(
                    db=db,
                    session=session,
                    merchant_id=principal.merchant_id,
                    risk_score=routing_decision.risk_score,
                    action="payout",
                    trigger_reason=routing_decision.reason_codes[0]
                    if routing_decision.reason_codes
                    else "POLICY_ENFORCED_SESSION_ISOLATION",
                    evidence_summary={
                        "payout_id": str(payout_id),
                        "amount": request.amount,
                        "currency": request.currency,
                        "recipient": request.recipient_email,
                        "risk_signals": risk_result.risk_signals,
                        "reason_codes": routing_decision.reason_codes,
                    },
                )

            # 8. Persist payout request and outcome record
            payout_record = PayoutRequestRecord(
                payout_id=payout_id,
                decision_id=routing_decision.decision_id,
                session_id=session.session_id,
                merchant_id=principal.merchant_id,
                user_id=principal.user_id,
                recipient_email=request.recipient_email,
                amount=request.amount,
                currency=request.currency,
                reference_note=request.reference_note,
                idempotency_key=request.idempotency_key,
                status=payout_status,
                provider_name=provider_name,
                provider_reference=provider_reference,
                provider_payload=provider_payload,
                executed_at=executed_at,
            )
            payout_repo.create(payout_record)

            # Update session activity and trust state
            session_repo.update_trust_state(
                session.session_id,
                routing_decision.trust_level.value,
                routing_decision.risk_score,
            )

            # 9. Build response
            response = PayoutResponse(
                payout_id=payout_id,
                decision_id=routing_decision.decision_id,
                session_id=session.session_id,
                status=payout_status,
                trust_level=routing_decision.trust_level,
                action=routing_decision.action,
                routing_destination=routing_decision.routing_destination,
                risk_score=routing_decision.risk_score,
                reason_codes=routing_decision.reason_codes,
                provider_reference=provider_reference,
                amount=request.amount,
                currency=request.currency,
                recipient_email=request.recipient_email,
                created_at=payout_record.created_at,
                is_duplicate=False,
            )

            # 10. Cache in idempotency record
            idempotency_repo.update_record(
                record=idem_record,
                status="completed",
                response_code=200,
                response_payload=response.model_dump(mode="json"),
            )

            return response

        except Exception as exc:
            db.rollback()

            # A payout that reached the provider but whose final outcome is
            # unknown must never be silently retried:
            #   * the provider returned a transaction id -> funds may have moved,
            #   * the provider timed out -> the outcome is ambiguous and the
            #     adapter itself demands reconciliation.
            # A definitive provider failure (rejection, rate limit, explicit
            # unsuccessful result) leaves the key safely retryable.
            provider_may_have_executed = False
            ambiguous_provider_outcome = False
            if provider_invoked and not provider_reported_failure:
                if provider_result is not None:
                    provider_may_have_executed = True
                elif isinstance(exc, ProviderTimeoutException):
                    provider_may_have_executed = True
                    ambiguous_provider_outcome = True

            if provider_may_have_executed:
                # CRITICAL SECURITY INVARIANT:
                # The payment provider was ALREADY executed (or may have been).
                # We MUST NOT mark idempotency as 'failed' because that would
                # allow retries to double-execute the payout!
                # Mark as 'provider_executed' and preserve provider_reference for reconciliation.
                try:
                    idempotency_repo.update_record(
                        record=idem_record,
                        status="provider_executed",
                        response_code=500,
                        response_payload={
                            "error": (
                                "PROVIDER_OUTCOME_AMBIGUOUS_RECONCILIATION_REQUIRED"
                                if ambiguous_provider_outcome
                                else "POST_PROVIDER_DB_FAILURE_RECONCILIATION_REQUIRED"
                            ),
                            "provider_transaction_id": (
                                provider_result.provider_transaction_id if provider_result else None
                            ),
                            "idempotency_key": request.idempotency_key,
                            "amount": request.amount,
                            "currency": request.currency,
                            "recipient": request.recipient_email,
                            "failure_details": str(exc),
                        },
                    )
                except Exception:
                    pass
            else:
                # Provider was never executed (or definitively failed without
                # moving funds). Safe to mark idempotency as failed so retry is allowed.
                try:
                    idempotency_repo.update_record(
                        record=idem_record,
                        status="failed",
                        response_code=500,
                        response_payload={"error": str(exc)},
                    )
                except Exception:
                    pass
            raise


def create_gateway_service(
    policy: TrustGatewayPolicy | None = None,
    risk_engine: IRiskEngineService | None = None,
    provider_adapter: IPaymentProviderAdapter | None = None,
    decoy_adapter: DecoyHoneyAdapter | None = None,
) -> TrustGatewayService:
    # Resolve the policy first, then derive the adapter from the policy's own
    # provider mode. Both halves of execution therefore share one explicit
    # decision instead of reading the configuration independently.
    resolved_policy = policy if policy is not None else get_gateway_policy()
    return TrustGatewayService(
        policy=resolved_policy,
        risk_engine=risk_engine if risk_engine is not None else get_risk_engine(),
        provider_adapter=(
            provider_adapter
            if provider_adapter is not None
            else get_payment_provider(resolved_policy.provider_mode)
        ),
        decoy_adapter=decoy_adapter if decoy_adapter is not None else get_decoy_provider(),
    )


def get_gateway_service() -> TrustGatewayService:
    return create_gateway_service()
