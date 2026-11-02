"""Schemas for the additive, advisory Intent Profiler.

The profiler is intentionally storage agnostic. The observation models below
accept only structured, derived fields that the Phase 3 loader can populate
from merchant-scoped records. Raw device identifiers, IP addresses, recipient
addresses, event metadata and free-text incident fields are not part of this
contract.
"""

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.intent.taxonomy import (
    ConfidenceReason,
    IntentConfidence,
    IntentEvidenceSource,
    IntentHypothesis,
    IntentSignalCode,
)


class IntentEvidenceReference(BaseModel):
    """One bounded, human-readable reference to structured evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: IntentEvidenceSource
    ref_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=280)
    occurred_at: datetime | None = None
    signal_codes: list[IntentSignalCode] = Field(default_factory=list, max_length=12)


class EventObservation(BaseModel):
    """Derived event facts only; no raw identifiers or metadata are accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    event_type: str = Field(min_length=1, max_length=64)
    action: str = Field(default="", max_length=64)
    occurred_at: datetime
    server_received_at: datetime
    device_hash: str | None = Field(default=None, max_length=64)
    location_bucket: str | None = Field(default=None, max_length=64)
    recipient_hash: str | None = Field(default=None, max_length=64)


class TwinBaselineObservation(BaseModel):
    """Derived behavioural baseline fields needed for novelty checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_count: int = Field(default=0, ge=0)
    amount_count: int = Field(default=0, ge=0)
    total_amount: float = Field(default=0.0, ge=0.0)
    confirmed_devices: list[str] = Field(default_factory=list, max_length=500)
    confirmed_locations: list[str] = Field(default_factory=list, max_length=500)
    payee_observations: dict[str, int] = Field(default_factory=dict)
    device_observations: dict[str, int] = Field(default_factory=dict)
    location_observations: dict[str, int] = Field(default_factory=dict)
    hour_histogram: dict[str, int] = Field(default_factory=dict)
    last_updated_at: datetime | None = None


class SequenceMarkerObservation(BaseModel):
    """A persisted cross-event marker. Recipient values are already hashed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    marker_id: str = Field(min_length=1, max_length=128)
    sequence_type: str = Field(min_length=1, max_length=64)
    recipient_hash: str | None = Field(default=None, max_length=64)
    occurred_at: datetime


class SessionRiskStateObservation(BaseModel):
    """The structured subset of the session risk ledger used by the profiler."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    current_score: float = Field(default=0.0, ge=0.0, le=100.0)
    registered_payees: list[str] = Field(default_factory=list, max_length=500)
    sequence_markers: list[SequenceMarkerObservation] = Field(default_factory=list, max_length=500)
    consumed_markers: list[str] = Field(default_factory=list, max_length=500)
    canary_seen: bool = False
    last_evaluated_at: datetime | None = None


class PayoutObservation(BaseModel):
    """Structured payout facts; free-text notes and recipient data are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payout_id: UUID
    amount: float = Field(default=0.0, ge=0.0)
    status: str = Field(default="", max_length=64)
    provider_name: str | None = Field(default=None, max_length=64)
    created_at: datetime
    executed_at: datetime | None = None


class CanaryObservation(BaseModel):
    """Metadata-only canary state. Secret tokens and tags are never included."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canary_id: UUID
    kind: str = Field(default="", max_length=64)
    armed: bool = False
    triggered_at: datetime | None = None


class IncidentObservation(BaseModel):
    """Structured incident facts only; titles, descriptions and summaries are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: UUID
    status: str = Field(default="", max_length=32)
    trigger_reason: str = Field(default="", max_length=96)
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    created_at: datetime


class SessionObservation(BaseModel):
    """Current authoritative session state, without raw network identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    trust_level: str = Field(default="NORMAL", max_length=32)
    status: str = Field(default="active", max_length=32)
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    last_activity_at: datetime | None = None


class IntentExtractionPolicy(BaseModel):
    """Bounded extraction policy. Defaults mirror the deterministic risk contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_baseline_samples: int = Field(default=10, ge=1)
    context_confirm_observations: int = Field(default=2, ge=1)
    payee_confirm_observations: int = Field(default=2, ge=1)
    large_payout_threshold: float = Field(default=5000.0, gt=0.0)
    large_payout_relative_factor: float = Field(default=3.0, gt=1.0)
    amount_baseline_min_samples: int = Field(default=1, ge=1)
    active_hour_fraction: float = Field(default=0.10, gt=0.0, le=1.0)
    min_hour_samples: int = Field(default=10, ge=1)
    hour_confirm_observations: int = Field(default=2, ge=1)
    hour_concentration_min: float = Field(default=0.25, gt=0.0, le=1.0)
    sequence_window_seconds: int = Field(default=1800, ge=1)
    velocity_window_seconds: int = Field(default=900, ge=1)
    velocity_min_registrations: int = Field(default=3, ge=2)
    velocity_min_payouts: int = Field(default=3, ge=2)
    default_timezone: str = Field(default="Asia/Kolkata", max_length=64)
    max_events: int = Field(default=200, ge=1, le=500)
    max_payouts: int = Field(default=200, ge=1, le=500)
    max_canaries: int = Field(default=50, ge=1, le=200)
    max_incidents: int = Field(default=50, ge=1, le=200)


class IntentSourceData(BaseModel):
    """Bounded source records supplied by the future merchant-scoped loader."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session: SessionObservation
    events: list[EventObservation] = Field(default_factory=list, max_length=500)
    twin: TwinBaselineObservation | None = None
    risk_state: SessionRiskStateObservation | None = None
    payouts: list[PayoutObservation] = Field(default_factory=list, max_length=500)
    canaries: list[CanaryObservation] = Field(default_factory=list, max_length=200)
    incidents: list[IncidentObservation] = Field(default_factory=list, max_length=200)


class IntentSignals(BaseModel):
    """Deterministic, explainable signal set derived from bounded source data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    event_count: int = Field(default=0, ge=0)
    unknown_event_count: int = Field(default=0, ge=0)
    auth_event_count: int = Field(default=0, ge=0)
    mfa_event_count: int = Field(default=0, ge=0)
    security_anomaly_count: int = Field(default=0, ge=0)
    pageview_count: int = Field(default=0, ge=0)
    heartbeat_count: int = Field(default=0, ge=0)
    payee_registration_count: int = Field(default=0, ge=0)
    payout_event_count: int = Field(default=0, ge=0)

    has_new_device: bool = False
    has_new_location: bool = False
    has_unusual_time: bool = False
    has_new_payee: bool = False
    has_large_payout: bool = False
    has_payee_add_then_payout: bool = False
    has_payee_registration_velocity: bool = False
    has_payout_velocity: bool = False
    has_canary_interaction: bool = False
    has_decoy_routing: bool = False
    blocked_payout_count: int = Field(default=0, ge=0)

    session_trust_level: str = Field(default="NORMAL", max_length=32)
    session_status: str = Field(default="active", max_length=32)
    session_risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    session_revoked: bool = False

    baseline_ready: bool = False
    baseline_provisional: bool = True
    hour_baseline_ready: bool = False
    has_payout_activity: bool = False

    max_payee_registrations_in_window: int = Field(default=0, ge=0)
    max_payouts_in_window: int = Field(default=0, ge=0)
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    evidence: list[IntentEvidenceReference] = Field(default_factory=list)


class IntentAnalysis(BaseModel):
    """Advisory classifier result. Confidence is ordinal, never probabilistic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary_intent: IntentHypothesis
    secondary_intents: list[IntentHypothesis] = Field(default_factory=list, max_length=2)
    confidence: IntentConfidence
    confidence_basis: list[ConfidenceReason] = Field(default_factory=list)
    evidence: list[IntentEvidenceReference] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    abstention_reason: str | None = Field(default=None, max_length=280)
    signals: IntentSignals
    advisory_only: Literal[True] = True
    requires_human_approval: Literal[True] = True
    classifier_version: str = Field(default="intent-classifier-v1", max_length=32)


class IntentProfileStatus(str, Enum):
    COMPLETE = "COMPLETE"
    FALLBACK = "FALLBACK"


class IntentProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_llm: bool = False


class IntentNarrative(BaseModel):
    """Narrative explanation only; it cannot alter classifier output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    headline: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1600)
    uncertainty_notes: list[str] = Field(default_factory=list, max_length=12)
    generated_by: Literal["deterministic", "llm"] = "deterministic"


class IntentProfileBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    merchant_id: UUID
    analysis: IntentAnalysis
    narrative: IntentNarrative
    redaction_applied: bool = True
    ai_used: bool = False
    model_name: str | None = Field(default=None, max_length=128)


class IntentProfileResponse(BaseModel):
    profile_id: UUID
    session_id: UUID
    merchant_id: UUID
    status: IntentProfileStatus
    ai_used: bool
    model_name: str | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    bundle: IntentProfileBundle


class IntentProfileListResponse(BaseModel):
    items: list[IntentProfileResponse]
    total: int
    page: int
    page_size: int
