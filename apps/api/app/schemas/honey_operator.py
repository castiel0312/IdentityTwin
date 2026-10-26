"""Operator read models for the synthetic honey workspace.

These projections are deliberately separate from the attacker-facing honey
routes: they never include canary secret values, never create synthetic data and
never execute a payment.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HoneyMerchantView(BaseModel):
    name: str
    country: str | None = None


class HoneyBalanceView(BaseModel):
    amount: float
    currency: str


class HoneyPayeeView(BaseModel):
    id: str
    name: str
    email: str


class HoneyTransactionView(BaseModel):
    id: str
    amount: float
    currency: str
    type: str
    date: str | None = None


class HoneyPayoutView(BaseModel):
    payout_batch_id: str
    batch_status: str
    amount: float
    currency: str
    recipient: str | None = None
    transaction_id: str | None = None


class HoneyActivityView(BaseModel):
    id: str
    method: str
    path: str
    occurred_at: str
    synthetic: bool = True


class HoneyWorkspaceSummary(BaseModel):
    session_id: UUID
    identity_id: UUID | None = None
    synthetic: bool = True
    merchant_name: str
    merchant_country: str | None = None
    balance: HoneyBalanceView
    payee_count: int = 0
    transaction_count: int = 0
    payout_count: int = 0
    activity_count: int = 0
    canary_count: int = 0
    canaries_triggered: int = 0
    containment_incident_id: UUID | None = None
    session_status: str
    updated_at: datetime


class HoneyWorkspaceListResponse(BaseModel):
    items: list[HoneyWorkspaceSummary]
    total: int
    page: int
    page_size: int


class HoneyCanaryView(BaseModel):
    canary_id: UUID
    session_id: UUID | None = None
    identity_id: UUID | None = None
    kind: str
    tag: str
    armed: bool
    triggered_at: datetime | None = None
    containment_incident_id: UUID | None = None
    containment_status: str | None = None


class HoneyCanaryListResponse(BaseModel):
    items: list[HoneyCanaryView]
    total: int


class HoneyWorkspaceDetailResponse(BaseModel):
    workspace: HoneyWorkspaceSummary
    merchant: HoneyMerchantView
    balance: HoneyBalanceView
    payees: list[HoneyPayeeView] = Field(default_factory=list)
    transactions: list[HoneyTransactionView] = Field(default_factory=list)
    payouts: list[HoneyPayoutView] = Field(default_factory=list)
    recent_activity: list[HoneyActivityView] = Field(default_factory=list)
    canaries: list[HoneyCanaryView] = Field(default_factory=list)
    containment_notes: list[str] = Field(default_factory=list)
    raw_world_meta: dict[str, Any] = Field(default_factory=dict)
