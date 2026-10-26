"""Dashboard analytics projections derived from persisted operational records."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AnalyticsRange(BaseModel):
    start: datetime
    end: datetime
    bucket: str = Field(description="hour | day")


class AnalyticsTotals(BaseModel):
    payouts_total: int = 0
    amount_total: float = 0.0
    amount_by_currency: dict[str, float] = Field(default_factory=dict)
    payouts_by_status: dict[str, int] = Field(default_factory=dict)
    payouts_by_trust_level: dict[str, int] = Field(default_factory=dict)
    payouts_requiring_step_up: int = 0
    decoy_routed: int = 0
    isolated_actions: int = 0
    reconciliation_required: int = 0
    provider_failures: int = 0
    agent_initiated: int = 0
    incidents_open: int = 0
    incidents_in_range: int = 0
    sessions_active: int = 0
    evidence_seals: int = 0


class AnalyticsBucket(BaseModel):
    bucket: str
    label: str
    payouts: int = 0
    amount: float = 0.0
    normal: int = 0
    restricted: int = 0
    decoy: int = 0
    isolated: int = 0
    incidents: int = 0


class RiskBucket(BaseModel):
    bucket: str
    min_score: float
    max_score: float
    count: int = 0


class ProviderOutcome(BaseModel):
    provider: str
    status: str
    count: int = 0


class RecentActivityItem(BaseModel):
    activity_id: str
    kind: str = Field(description="event | payout | incident")
    occurred_at: datetime
    title: str
    summary: str | None = None
    severity: str | None = None
    risk_score: float | None = None
    trust_level: str | None = None
    event_type: str | None = None
    session_id: UUID | None = None
    payout_id: UUID | None = None
    incident_id: UUID | None = None


class AnalyticsOverviewResponse(BaseModel):
    range: AnalyticsRange
    generated_at: datetime
    totals: AnalyticsTotals
    timeline: list[AnalyticsBucket] = Field(default_factory=list)
    risk_histogram: list[RiskBucket] = Field(default_factory=list)
    provider_outcomes: list[ProviderOutcome] = Field(default_factory=list)
    recent_activity: list[RecentActivityItem] = Field(default_factory=list)
    truncated: bool = Field(
        default=False,
        description=(
            "True when the requested range exceeded the server-side scan cap. "
            "Metrics are then explicitly partial and must not be presented as global."
        ),
    )
