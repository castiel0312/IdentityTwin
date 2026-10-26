"""Risk decision read models for the Risk Intelligence console."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.risk.schemas import RiskContribution, SequenceMarker
from app.schemas.payout_queries import PayoutListItem
from app.schemas.sessions import SessionResponse


class RiskDecisionItem(BaseModel):
    decision_id: UUID
    session_id: UUID
    payout_id: UUID | None = None
    risk_score: float
    trust_level: str
    action: str
    routing_destination: str
    reason_codes: list[str] = Field(default_factory=list)
    risk_signals: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime


class RiskDecisionListResponse(BaseModel):
    items: list[RiskDecisionItem]
    total: int
    page: int
    page_size: int


class RiskSignalDefinition(BaseModel):
    name: str
    weight: float
    description: str


class RiskConfigView(BaseModel):
    thresholds: dict[str, float]
    signals: list[RiskSignalDefinition]
    sequence_window_seconds: int
    min_samples: int
    provisional_factor: float
    decay_points_per_event: float
    default_timezone: str
    protected_actions: list[str] = Field(default_factory=list)


class RiskTwinComparison(BaseModel):
    is_provisional: bool
    sample_count: int
    confirmed_device_count: int
    confirmed_location_count: int
    confirmed_payee_count: int
    pending_payee_count: int


class RiskDecisionDetailResponse(BaseModel):
    decision: RiskDecisionItem
    session: SessionResponse
    payout: PayoutListItem | None = None
    signals: list[RiskSignalDefinition] = Field(default_factory=list)
    contributions: list[RiskContribution] = Field(default_factory=list)
    sequence_markers: list[SequenceMarker] = Field(default_factory=list)
    twin: RiskTwinComparison | None = None
    limitations: list[str] = Field(default_factory=list)
