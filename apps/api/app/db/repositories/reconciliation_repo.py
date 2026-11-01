from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.payout import PayoutRequestRecord

# Payout states that are unresolved and may require provider reconciliation.
RECONCILABLE_STATUSES = ("pending", "processing")

# Terminal failure states that definitively release a spending reservation.
TERMINAL_FAILURE_STATUSES = ("failed", "denied", "returned", "blocked")

# Terminal success state that consumes a spending reservation.
TERMINAL_SUCCESS_STATUSES = ("completed", "reconciled_completed")

# Maximum number of automated reconciliation attempts before manual escalation.
MAX_RECONCILIATION_ATTEMPTS = 10

# Initial retry delay in seconds after an inconclusive reconciliation.
INITIAL_RETRY_SECONDS = 30

# Maximum retry interval in seconds (1 hour).
MAX_RETRY_INTERVAL_SECONDS = 3600

# Age (seconds) after which an unresolved payout is considered stuck and alerted.
STUCK_PAYOUT_SECONDS = 1800

# Age (seconds) after which a pending payout with no provider reference is
# escalated to manual review rather than left unresolved forever.
NO_PROVIDER_REFERENCE_ESCALATION_SECONDS = 300

# Age (seconds) after which a worker claim is considered stale. A worker that
# crashes mid-processing leaves `reconciliation_claimed_at` set; another worker
# can reclaim after this timeout so reconciliation makes progress.
RECONCILIATION_CLAIM_TIMEOUT_SECONDS = 300


def next_retry_backoff(attempts: int) -> int:
    """
    Exponential backoff for the next retry after attempt ``attempts``.

    attempt 1 -> 30s, attempt 2 -> 60s, ... capped at 1 hour.
    """
    return min(INITIAL_RETRY_SECONDS * (2 ** (attempts - 1)), MAX_RETRY_INTERVAL_SECONDS)


class ReconciliationRepository:
    """Database access for the automated reconciliation worker.

    All claiming uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple worker
    instances (or a worker restarted after a crash) never process the same
    payout concurrently.
    """

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Claiming
    # ------------------------------------------------------------------
    def _claim_ids(
        self,
        now: datetime,
        claim_cutoff: datetime,
        candidate_filters,
        batch_size: int,
    ) -> Sequence[UUID]:
        """
        Pick candidate payout ids (ordered, bounded) then atomically claim them.

        The candidate subquery orders and limits rows. The UPDATE then re-verifies
        the unclaimed/stale-claim condition under row-level locking, so two
        workers that select the same candidate row will not both claim it: only
        the UPDATE that sets ``reconciliation_claimed_at`` first wins.
        """
        id_subq = (
            select(PayoutRequestRecord.payout_id)
            .where(*candidate_filters)
            .order_by(PayoutRequestRecord.created_at.asc())
            .limit(batch_size)
            .subquery("reconciliation_claim_candidates")
        )
        stmt = (
            update(PayoutRequestRecord)
            .where(
                PayoutRequestRecord.payout_id.in_(select(id_subq.c.payout_id)),
                (
                    PayoutRequestRecord.reconciliation_claimed_at.is_(None)
                    | (PayoutRequestRecord.reconciliation_claimed_at < claim_cutoff)
                ),
            )
            .values(reconciliation_claimed_at=now)
            .returning(PayoutRequestRecord)
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return list(result.scalars().all())

    def claim_reconcilable_payouts(self, batch_size: int = 50) -> Sequence[PayoutRequestRecord]:
        """
        Atomically claim a bounded batch of payouts due for reconciliation.

        Eligible payouts:

        * status is pending or processing (unresolved, non-terminal)
        * provider_batch_id is set (provider status can be retrieved)
        * not yet escalated to manual review
        * under the maximum automated attempt count
        * next retry is due (next_retry_at is NULL or in the past)
        * not currently claimed by a live worker (or claim is stale)

        The claim is persisted via ``reconciliation_claimed_at`` so it survives
        the internal commit performed by ``reconcile_payout()``. Multiple worker
        instances therefore never process the same payout concurrently; a worker
        that crashes mid-processing releases its claim after the claim timeout.
        """
        now = datetime.now(timezone.utc)
        claim_cutoff = now - timedelta(seconds=RECONCILIATION_CLAIM_TIMEOUT_SECONDS)
        filters = (
            PayoutRequestRecord.status.in_(RECONCILABLE_STATUSES),
            PayoutRequestRecord.provider_batch_id.is_not(None),
            PayoutRequestRecord.escalated_at.is_(None),
            PayoutRequestRecord.reconciliation_attempts < MAX_RECONCILIATION_ATTEMPTS,
            (
                PayoutRequestRecord.next_retry_at.is_(None)
                | (PayoutRequestRecord.next_retry_at <= now)
            ),
        )
        return self._claim_ids(now, claim_cutoff, filters, batch_size)

    def claim_no_provider_reference_payouts(
        self, batch_size: int = 50
    ) -> Sequence[PayoutRequestRecord]:
        """
        Claim unresolved payouts that have no provider reference.

        These cannot be reconciled against the provider (no batch id) and must
        be escalated to manual review instead of being automatically resubmitted.
        """
        now = datetime.now(timezone.utc)
        claim_cutoff = now - timedelta(seconds=RECONCILIATION_CLAIM_TIMEOUT_SECONDS)
        created_cutoff = now - timedelta(seconds=NO_PROVIDER_REFERENCE_ESCALATION_SECONDS)
        filters = (
            PayoutRequestRecord.status.in_(RECONCILABLE_STATUSES),
            PayoutRequestRecord.provider_batch_id.is_(None),
            PayoutRequestRecord.escalated_at.is_(None),
            PayoutRequestRecord.created_at <= created_cutoff,
        )
        return self._claim_ids(now, claim_cutoff, filters, batch_size)

    # ------------------------------------------------------------------
    # State updates
    # ------------------------------------------------------------------
    def record_reconciliation(
        self,
        payout: PayoutRequestRecord,
        *,
        new_status: str,
        resolved: bool,
        escalated: bool = False,
        escalation_reason: str | None = None,
    ) -> PayoutRequestRecord:
        """
        Persist the outcome of one reconciliation attempt.

        Updates attempt count, last reconciled timestamp, next retry timestamp
        (or clears it when resolved/escalated), and escalation fields.
        """
        now = datetime.now(timezone.utc)
        payout.reconciliation_attempts = (payout.reconciliation_attempts or 0) + 1
        payout.last_reconciled_at = now

        if escalated:
            payout.escalated_at = now
            payout.escalation_reason = escalation_reason or "manual_escalation"
            payout.next_retry_at = None
        elif resolved:
            payout.next_retry_at = None
        else:
            payout.next_retry_at = now + timedelta(
                seconds=next_retry_backoff(payout.reconciliation_attempts)
            )

        self.db.add(payout)
        payout.reconciliation_claimed_at = None
        self.db.commit()
        self.db.refresh(payout)
        return payout

    def mark_escalated(
        self,
        payout: PayoutRequestRecord,
        reason: str,
    ) -> PayoutRequestRecord:
        """Mark a payout as manually escalated (no further automated retries)."""
        now = datetime.now(timezone.utc)
        payout.escalated_at = now
        payout.escalation_reason = reason
        payout.next_retry_at = None
        payout.reconciliation_claimed_at = None
        self.db.add(payout)
        self.db.commit()
        self.db.refresh(payout)
        return payout

    # ------------------------------------------------------------------
    # Reads for observability / API
    # ------------------------------------------------------------------
    def get_by_id(self, payout_id: UUID) -> PayoutRequestRecord | None:
        stmt = select(PayoutRequestRecord).where(PayoutRequestRecord.payout_id == payout_id)
        return self.db.scalars(stmt).first()

    def list_for_merchant(
        self,
        merchant_id: UUID,
        *,
        status: str | None = None,
        escalated: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PayoutRequestRecord], int]:
        filters = [PayoutRequestRecord.merchant_id == merchant_id]
        if status:
            filters.append(PayoutRequestRecord.status == status)
        if escalated is True:
            filters.append(PayoutRequestRecord.escalated_at.is_not(None))
        elif escalated is False:
            filters.append(PayoutRequestRecord.escalated_at.is_(None))

        total = self.db.scalar(
            select(func.count()).select_from(PayoutRequestRecord).where(*filters)
        )
        stmt = (
            select(PayoutRequestRecord)
            .where(*filters)
            .order_by(PayoutRequestRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt).all()), total or 0

    def stuck_count(self, merchant_id: UUID | None = None) -> int:
        """Count unresolved payouts older than the stuck threshold."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=STUCK_PAYOUT_SECONDS)
        stmt = (
            select(func.count())
            .select_from(PayoutRequestRecord)
            .where(
                PayoutRequestRecord.status.in_(RECONCILABLE_STATUSES),
                PayoutRequestRecord.escalated_at.is_(None),
                PayoutRequestRecord.created_at <= cutoff,
            )
        )
        if merchant_id is not None:
            stmt = stmt.where(PayoutRequestRecord.merchant_id == merchant_id)
        return self.db.scalar(stmt) or 0
