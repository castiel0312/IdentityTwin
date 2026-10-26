"""Read-only payout projections used by the operations console.

These schemas never introduce a second decision path: every value is projected
from the payout, risk decision, idempotency and agentic audit records that the
Trust Gateway already persisted.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PayoutListItem(BaseModel):
    payout_id: UUID
    merchant_id: UUID
    session_id: UUID
    amount: float
    currency: str
    recipient_email: str
    reference_note: str | None = None

    risk_score: float
    trust_level: str
    action: str
    routing_destination: str
    reason_codes: list[str] = Field(default_factory=list)

    status: str
    provider_name: str
    provider_reference: str | None = None
    created_at: datetime
    executed_at: datetime | None = None

    reconciliation_required: bool = False
    agent_id: UUID | None = None
    agent_display_name: str | None = None


class PayoutListResponse(BaseModel):
    items: list[PayoutListItem]
    total: int
    page: int
    page_size: int


class PayoutRequestView(BaseModel):
    recipient_email: str
    amount: float
    currency: str
    reference_note: str | None = None
    idempotency_key: str


class PayoutDecisionView(BaseModel):
    decision_id: UUID
    risk_score: float
    trust_level: str
    action: str
    routing_destination: str
    reason_codes: list[str] = Field(default_factory=list)
    risk_signals: dict[str, Any] = Field(default_factory=dict)
    signal_weights: dict[str, float] = Field(default_factory=dict)
    evaluated_at: datetime


class PayoutProviderView(BaseModel):
    name: str
    reference: str | None = None
    executed_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PayoutIdempotencyView(BaseModel):
    status: str
    request_hash: str
    response_code: int | None = None
    expires_at: datetime
    updated_at: datetime
    reconciliation_required: bool = False


class PayoutSessionView(BaseModel):
    session_id: UUID
    status: str
    trust_level: str
    risk_score: float
    device_fingerprint: str | None = None
    ip_address: str | None = None
    created_at: datetime
    last_activity_at: datetime


class PayoutIncidentReference(BaseModel):
    incident_id: UUID
    title: str
    severity: str
    status: str
    risk_score: float
    trigger_reason: str
    sealed_at: datetime | None = None
    created_at: datetime


class PayoutEvidenceEntry(BaseModel):
    seq: int
    event_ref: str
    hash: str
    created_at: datetime


class PayoutEvidenceSeal(BaseModel):
    seal_id: UUID
    start_seq: int
    end_seq: int
    head_hash: str
    sealed_at: datetime


class PayoutEvidenceView(BaseModel):
    entries: list[PayoutEvidenceEntry] = Field(default_factory=list)
    seal: PayoutEvidenceSeal | None = None


class PayoutTimelineItem(BaseModel):
    key: str
    label: str
    status: str
    occurred_at: datetime | None = None
    detail: str | None = None


class PayoutStepUpView(BaseModel):
    required: bool = False
    verified: bool = False
    evidence: str | None = None


class PayoutAgentView(BaseModel):
    agent_id: UUID
    display_name: str
    grant_id: UUID | None = None
    status: str
    intent: str | None = None
    audit_id: UUID


class PayoutDetailResponse(BaseModel):
    payout: PayoutListItem
    request: PayoutRequestView
    decision: PayoutDecisionView
    provider: PayoutProviderView
    idempotency: PayoutIdempotencyView | None = None
    session: PayoutSessionView
    incidents: list[PayoutIncidentReference] = Field(default_factory=list)
    evidence: PayoutEvidenceView = Field(default_factory=PayoutEvidenceView)
    step_up: PayoutStepUpView = Field(default_factory=PayoutStepUpView)
    agent: PayoutAgentView | None = None
    timeline: list[PayoutTimelineItem] = Field(default_factory=list)
