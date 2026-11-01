from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReconciliationPayoutSummary(BaseModel):
    """Administrative view of a payout's reconciliation state.

    Deliberately excludes sensitive recipient information and provider
    credentials. Scoped to a single merchant.
    """

    model_config = ConfigDict(from_attributes=True)

    payout_id: UUID
    merchant_id: UUID
    status: str = Field(description="Current payout state-machine status")
    provider_batch_id: str | None = Field(
        None, description="Provider batch id, only present when a provider reference exists"
    )
    provider_name: str | None = None
    reconciliation_attempts: int = Field(
        0, description="Number of automated reconciliation attempts made"
    )
    last_reconciled_at: datetime | None = None
    next_retry_at: datetime | None = None
    escalated_at: datetime | None = None
    escalation_reason: str | None = None
    created_at: datetime
    amount: float


class ReconciliationListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[ReconciliationPayoutSummary]
    total: int
    page: int
    page_size: int


class ReconciliationStats(BaseModel):
    """Stuck-payout and reconciliation metrics for an analyst console."""

    model_config = ConfigDict(from_attributes=True)

    merchant_id: UUID
    total_unresolved: int = Field(
        0, description="Payouts still pending or processing and not escalated"
    )
    total_escalated: int = Field(0, description="Payouts escalated to manual review")
    stuck_payouts: int = Field(
        0, description="Unresolved payouts older than the stuck threshold (30 minutes)"
    )
    total_pending_retry: int = Field(0, description="Payouts awaiting their next automated retry")


class ManualReconcileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payout_id: UUID
    status: str
    reconciled: bool = Field(True, description="Whether the payout reached a terminal state")
    message: str


class EscalateRequest(BaseModel):
    reason: str = Field(
        "manual_escalation", min_length=1, max_length=255, description="Escalation reason"
    )
