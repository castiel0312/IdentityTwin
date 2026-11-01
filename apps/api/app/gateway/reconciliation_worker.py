import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.repositories.agent_repo import AgentRepository
from app.db.repositories.reconciliation_repo import (
    MAX_RECONCILIATION_ATTEMPTS,
    TERMINAL_FAILURE_STATUSES,
    TERMINAL_SUCCESS_STATUSES,
    ReconciliationRepository,
)
from app.db.session import SessionLocal
from app.gateway.service import TrustGatewayService

logger = logging.getLogger("identitytwin.reconciliation")


class ReconciliationWorker:
    """
    Background reconciliation worker for the Trust Gateway.

    Runs inside the FastAPI application process (no Celery/Redis). Every
    ``interval`` seconds it claims a bounded batch of payouts due for
    reconciliation using PostgreSQL ``SELECT ... FOR UPDATE SKIP LOCKED`` so
    multiple worker instances never process the same payout concurrently, then
    reconciles each against the payment provider via the existing
    ``TrustGatewayService.reconcile_payout()``.

    All database work runs in a worker thread (``asyncio.to_thread``) so the
    FastAPI event loop is never blocked. The worker stops gracefully when the
    application shuts down.
    """

    def __init__(
        self,
        gateway_service: TrustGatewayService,
        session_factory: sessionmaker | None = None,
        interval: float | None = None,
        batch_size: int = 50,
    ):
        self.gateway_service = gateway_service
        self.session_factory = session_factory or SessionLocal
        self.interval = (
            interval
            if interval is not None
            else float(getattr(settings, "RECONCILIATION_INTERVAL_SECONDS", 300))
        )
        self.batch_size = batch_size
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run(), name="reconciliation-worker")
            logger.info("reconciliation.worker.started", extra={"interval_seconds": self.interval})

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=15.0)
            except TimeoutError:
                logger.warning("reconciliation.worker.stop_timeout")
                self._task.cancel()
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("reconciliation.worker.stopped")

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------
    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                # Database access is synchronous SQLAlchemy; run it in a worker
                # thread so the FastAPI event loop stays free.
                await asyncio.to_thread(self._reconcile_cycle)
            except asyncio.CancelledError:
                break
            except Exception:  # pragma: no cover - defensive cycle boundary
                logger.exception("reconciliation.cycle_failed")
            # Wait for the next tick, or return early if stopping.
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval)
            except TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Reconciliation cycle
    # ------------------------------------------------------------------
    def _reconcile_cycle(self) -> None:
        db: Session = self.session_factory()
        try:
            repo = ReconciliationRepository(db)

            claimed = repo.claim_reconcilable_payouts(batch_size=self.batch_size)
            logger.info(
                "reconciliation.cycle.started",
                extra={"claimed": len(claimed), "batch_size": self.batch_size},
            )

            for payout in claimed:
                self._process_payout(db, payout)

            # Escalate unresolved payouts that have no provider reference:
            # they cannot be reconciled against the provider and must never be
            # automatically resubmitted.
            no_reference = repo.claim_no_provider_reference_payouts(batch_size=self.batch_size)
            for payout in no_reference:
                repo.mark_escalated(payout, reason="no_provider_reference")
                logger.warning(
                    "reconciliation.escalated.no_provider_reference",
                    extra={
                        "payout_id": str(payout.payout_id),
                        "merchant_id": str(payout.merchant_id),
                        "status": payout.status,
                    },
                )
                self._alert_stuck(payout)

            logger.info(
                "reconciliation.cycle.completed",
                extra={"reconciled": len(claimed), "escalated_no_reference": len(no_reference)},
            )
        finally:
            db.close()

    def _process_payout(self, db: Session, payout) -> None:
        repo = ReconciliationRepository(db)
        payout_id = payout.payout_id
        merchant_id = payout.merchant_id
        old_status = payout.status

        # Delegate provider status retrieval and state transition to the
        # existing manual reconciliation entry point. It is idempotent and
        # never regresses terminal states.
        result = self.gateway_service.reconcile_payout(db, payout_id, merchant_id)
        # reconcile_payout commits internally and expires session state.
        db.refresh(payout)
        new_status = payout.status

        if result is None:
            logger.warning(
                "reconciliation.payout_not_found",
                extra={"payout_id": str(payout_id), "merchant_id": str(merchant_id)},
            )
            return

        # Exactly-once reservation consumption/release on a real status
        # transition. Terminal states cannot regress, so this cannot double
        # apply even if the payout is revisited after a restart.
        if new_status != old_status:
            self._apply_reservation_outcome(db, payout, new_status)

        if new_status in TERMINAL_SUCCESS_STATUSES:
            repo.record_reconciliation(payout, new_status=new_status, resolved=True)
            logger.info(
                "reconciliation.resolved.success",
                extra={
                    "payout_id": str(payout_id),
                    "merchant_id": str(merchant_id),
                    "old_status": old_status,
                    "new_status": new_status,
                },
            )
            return

        if new_status in TERMINAL_FAILURE_STATUSES:
            repo.record_reconciliation(payout, new_status=new_status, resolved=True)
            logger.info(
                "reconciliation.resolved.failure",
                extra={
                    "payout_id": str(payout_id),
                    "merchant_id": str(merchant_id),
                    "old_status": old_status,
                    "new_status": new_status,
                },
            )
            return

        # Unresolved (processing / unknown / unchanged pending): retry with
        # exponential backoff, or escalate to manual review when automated
        # attempts are exhausted.
        this_attempt = (payout.reconciliation_attempts or 0) + 1
        if this_attempt >= MAX_RECONCILIATION_ATTEMPTS:
            repo.record_reconciliation(
                payout,
                new_status=new_status,
                resolved=False,
                escalated=True,
                escalation_reason="max_reconciliation_attempts_exhausted",
            )
            logger.error(
                "reconciliation.escalated.max_attempts",
                extra={
                    "payout_id": str(payout_id),
                    "merchant_id": str(merchant_id),
                    "status": new_status,
                    "attempts": this_attempt,
                },
            )
            self._alert_stuck(payout)
            return

        repo.record_reconciliation(payout, new_status=new_status, resolved=False)
        next_retry = payout.next_retry_at
        logger.info(
            "reconciliation.unresolved.retry_scheduled",
            extra={
                "payout_id": str(payout_id),
                "merchant_id": str(merchant_id),
                "status": new_status,
                "attempts": this_attempt,
                "next_retry_at": next_retry.isoformat() if next_retry else None,
            },
        )
        self._alert_stuck(payout)

    def _apply_reservation_outcome(self, db: Session, payout, new_status: str) -> None:
        """Consume or release the spending reservation exactly once.

        Ties the payout to its agent authorization grant via the session.
        Payouts without a grant (human-initiated) have no reservation to touch.
        """

        grant = self._find_active_grant(db, payout.session_id, payout.merchant_id)
        if grant is None:
            logger.debug(
                "reconciliation.reservation.no_grant",
                extra={"payout_id": str(payout.payout_id)},
            )
            return

        amount = float(payout.amount)
        agent_repo = AgentRepository(db)
        if new_status == "completed":
            agent_repo.consume_reservation(grant.grant_id, amount)
            logger.info(
                "reconciliation.reservation.consumed",
                extra={
                    "payout_id": str(payout.payout_id),
                    "grant_id": str(grant.grant_id),
                    "amount": amount,
                },
            )
        elif new_status in TERMINAL_FAILURE_STATUSES:
            agent_repo.release_reservation(grant.grant_id, amount)
            logger.info(
                "reconciliation.reservation.released",
                extra={
                    "payout_id": str(payout.payout_id),
                    "grant_id": str(grant.grant_id),
                    "amount": amount,
                },
            )

    def _find_active_grant(self, db: Session, session_id, merchant_id):
        from app.models.agent import AgentAuthorizationGrant

        now = datetime.now(timezone.utc)
        stmt = (
            select(AgentAuthorizationGrant)
            .where(
                AgentAuthorizationGrant.session_id == session_id,
                AgentAuthorizationGrant.merchant_id == merchant_id,
                AgentAuthorizationGrant.revoked_at.is_(None),
                (
                    AgentAuthorizationGrant.expires_at.is_(None)
                    | (AgentAuthorizationGrant.expires_at > now)
                ),
            )
            .order_by(AgentAuthorizationGrant.issued_at.desc())
            .limit(1)
        )
        return db.scalars(stmt).first()

    def _alert_stuck(self, payout) -> None:
        """Log an alert when a payout remains unresolved past the stuck threshold."""
        now = datetime.now(timezone.utc)
        created = payout.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_seconds = (now - created).total_seconds()
        if age_seconds > 1800:
            logger.error(
                "reconciliation.alert.stuck_payout",
                extra={
                    "payout_id": str(payout.payout_id),
                    "merchant_id": str(payout.merchant_id),
                    "status": payout.status,
                    "attempts": payout.reconciliation_attempts,
                    "age_seconds": age_seconds,
                    "escalated": payout.escalated_at is not None,
                },
            )
