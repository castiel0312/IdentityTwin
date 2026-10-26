"""Session investigation projection."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.risk.schemas import RiskContribution
from app.schemas.identities import TwinSummary
from app.schemas.incidents import IncidentResponse
from app.schemas.payout_queries import PayoutListItem
from app.schemas.sessions import SessionResponse


class SessionEventView(BaseModel):
    event_id: UUID
    event_type: str
    action: str
    occurred_at: datetime
    server_received_at: datetime
    device_id: str | None = None
    ip_address: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionRiskLedgerView(BaseModel):
    current_score: float = 0.0
    carried_forward: float = 0.0
    raw_points_sum: float = 0.0
    decay_points_total: float = 0.0
    canary_points: float = 0.0
    canary_seen: bool = False
    latched_signals: list[str] = Field(default_factory=list)
    contributions: list[RiskContribution] = Field(default_factory=list)
    last_evaluated_at: datetime | None = None


class SequenceEventView(BaseModel):
    event_id: UUID
    event_type: str
    action: str
    occurred_at: datetime
    elapsed_seconds: float


class SessionSequenceView(BaseModel):
    marker_id: str
    sequence_type: str
    occurred_at: datetime
    elapsed_seconds: float = 0.0
    recipient_hash: str | None = None
    events: list[SequenceEventView] = Field(default_factory=list)


class SessionSequencesView(BaseModel):
    window_seconds: int
    markers: list[SessionSequenceView] = Field(default_factory=list)


class SessionCanaryView(BaseModel):
    canary_id: UUID
    kind: str
    tag: str
    armed: bool
    triggered_at: datetime | None = None


class SessionActivityResponse(BaseModel):
    session: SessionResponse
    events: list[SessionEventView] = Field(default_factory=list)
    payouts: list[PayoutListItem] = Field(default_factory=list)
    incidents: list[IncidentResponse] = Field(default_factory=list)
    risk_ledger: SessionRiskLedgerView = Field(default_factory=SessionRiskLedgerView)
    sequences: SessionSequencesView
    canaries: list[SessionCanaryView] = Field(default_factory=list)
    devices: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    twin: TwinSummary | None = None
