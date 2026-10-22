import uuid
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sessions import TrustLevel

ContributionKind = Literal["signal", "carry_forward", "decay", "isolation_floor"]


class RiskEvaluationRequest(BaseModel):
    session_id: UUID
    merchant_id: UUID
    user_id: UUID
    action_type: str = "payout"
    amount: float = 0.0
    recipient: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    # --- Additive Person 2 fields (all optional, existing callers unaffected) ---
    occurred_at: datetime | None = Field(
        None, description="Authoritative event timestamp used for hour-of-day baselines"
    )
    event_id: UUID | None = Field(None, description="Stable event identifier for deduplication")
    device_id: str | None = Field(
        None, description="Raw device fingerprint (hashed before storage)"
    )
    ip_address: str | None = Field(None, description="Client IP address (bucketed before storage)")
    event_type: str | None = Field(None, description="Standardized event classification")


class RiskContribution(BaseModel):
    """A single, auditable contribution to a session risk score."""

    name: str
    points: float
    reason_code: str
    kind: ContributionKind = "signal"
    event_id: str | None = None
    occurred_at: datetime | None = None
    latch_key: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class FeatureVector(BaseModel):
    """Deterministic behavioural features extracted for a single event."""

    event_type: str = ""
    action_type: str = ""
    amount: float = 0.0
    recipient_hash: str | None = None
    device_hash: str | None = None
    location_bucket: str | None = None
    local_hour: int | None = None
    is_payee_registration: bool = False
    is_payout: bool = False
    is_new_device: bool = False
    is_new_location: bool = False
    is_unusual_hour: bool = False
    is_new_payee: bool = False
    is_large_payout: bool = False
    twin_provisional: bool = True
    twin_sample_count: int = 0
    baseline_ready: bool = False
    notes: list[str] = Field(default_factory=list)


class TwinSnapshot(BaseModel):
    """Pure (storage agnostic) behavioural twin baseline for one identity."""

    merchant_id: UUID
    user_id: UUID
    sample_count: int = 0
    confirmed_devices: list[str] = Field(default_factory=list)
    confirmed_locations: list[str] = Field(default_factory=list)
    payee_observations: dict[str, int] = Field(default_factory=dict)
    device_observations: dict[str, int] = Field(default_factory=dict)
    location_observations: dict[str, int] = Field(default_factory=dict)
    hour_histogram: dict[str, int] = Field(default_factory=dict)
    total_amount: float = 0.0
    amount_count: int = 0
    last_updated_at: datetime | None = None

    def confirmed_payees(self, confirm_observations: int) -> set[str]:
        return {
            recipient
            for recipient, observations in self.payee_observations.items()
            if observations >= confirm_observations
        }

    def pending_payees(self, confirm_observations: int) -> set[str]:
        return {
            recipient
            for recipient, observations in self.payee_observations.items()
            if observations < confirm_observations
        }


class SequenceMarker(BaseModel):
    """Marker used to correlate multi-event attack sequences inside a session."""

    marker_id: str
    sequence_type: str
    recipient_hash: str | None = None
    occurred_at: datetime


class SessionRiskState(BaseModel):
    """Durable per-session risk ledger owned by the risk engine."""

    session_id: UUID
    merchant_id: UUID
    user_id: UUID
    carried_forward: float = 0.0
    raw_points_sum: float = 0.0
    decay_points_total: float = 0.0
    current_score: float = 0.0
    canary_points: float = 0.0
    contributions: list[RiskContribution] = Field(default_factory=list)
    latched_signals: list[str] = Field(default_factory=list)
    fired_payees: list[str] = Field(default_factory=list)
    registered_payees: list[str] = Field(default_factory=list)
    sequence_markers: list[SequenceMarker] = Field(default_factory=list)
    consumed_markers: list[str] = Field(default_factory=list)
    event_fingerprints: list[str] = Field(default_factory=list)
    canary_seen: bool = False
    updated_at: datetime | None = None


class RiskEvaluationResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision_id: UUID = Field(default_factory=uuid.uuid4)
    session_id: UUID
    risk_score: float = Field(ge=0.0, le=100.0, description="Evaluated risk score (0-100 scale)")
    evaluated_trust_level: TrustLevel = Field(
        description="Evaluated trust level before policy rules are applied"
    )
    risk_signals: dict[str, float] = Field(
        default_factory=dict,
        description="Named behavioral and security risk signals contributing to the score",
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="Named explanation codes for the risk assessment",
    )
    evaluated_at: datetime
    # --- Additive Person 2 fields (existing consumers keep working unchanged) ---
    contributions: list[RiskContribution] = Field(
        default_factory=list,
        description="Full auditable ledger of every score contribution for this evaluation",
    )
    features: FeatureVector | None = Field(
        None, description="Behavioural feature vector used for the evaluation"
    )
    twin_provisional: bool = Field(
        True, description="True while the identity twin has not collected enough baseline samples"
    )
    twin_sample_count: int = Field(
        0, description="Number of baseline observations held by the twin"
    )
    raw_points_sum: float = Field(
        0.0, description="Sum of anomaly signal points in this evaluation"
    )
    decay_points: float = Field(0.0, description="Points removed by behavioural decay")
    session_carried_forward: float = Field(
        0.0, description="Score inherited from the session before the engine owned it"
    )
    duplicate_event: bool = Field(
        False, description="True when the event was ignored as a duplicate"
    )
    twin_updated: bool = Field(False, description="True when the twin baseline was updated")
