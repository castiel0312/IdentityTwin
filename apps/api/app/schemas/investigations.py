from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InvestigationStatus(str, Enum):
    COMPLETE = "COMPLETE"
    FALLBACK = "FALLBACK"


class InvestigationFindingType(str, Enum):
    CANARY_INTERACTION = "CANARY_INTERACTION"
    BLOCKED_PAYOUT = "BLOCKED_PAYOUT"
    DECOY_CONTAINMENT = "DECOY_CONTAINMENT"
    HIGH_RISK_DECISION = "HIGH_RISK_DECISION"
    NEW_DEVICE = "NEW_DEVICE"
    NEW_LOCATION = "NEW_LOCATION"
    UNUSUAL_TIME = "UNUSUAL_TIME"
    NEW_PAYEE = "NEW_PAYEE"
    LARGE_PAYOUT = "LARGE_PAYOUT"
    NEW_PAYEE_LARGE_PAYOUT = "NEW_PAYEE_LARGE_PAYOUT"
    PAYEE_ADD_THEN_PAYOUT = "PAYEE_ADD_THEN_PAYOUT"
    SESSION_REVOKED = "SESSION_REVOKED"
    EVIDENCE_INTEGRITY = "EVIDENCE_INTEGRITY"


class InvestigationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus: str | None = Field(
        None,
        max_length=200,
        description="Optional analyst focus. Recorded in the bundle; never used to override routing.",
    )
    use_llm: bool = Field(
        True,
        description=(
            "Request an LLM narrative when the deployment enables it. Deterministic "
            "analysis and fallback narrative always run. The LLM never scores or routes."
        ),
    )


class EvidenceReference(BaseModel):
    source: Literal[
        "incident",
        "session",
        "risk_decision",
        "payout",
        "event",
        "evidence_chain",
        "canary",
    ]
    ref_id: str
    summary: str
    occurred_at: datetime | None = None
    evidence_seq: int | None = None
    evidence_hash: str | None = None


class InvestigationFinding(BaseModel):
    finding_id: str
    finding_type: InvestigationFindingType
    title: str
    severity: str
    explanation: str
    evidence: list[EvidenceReference] = Field(default_factory=list)
    deterministic: bool = True


class InvestigationRecommendation(BaseModel):
    action: str
    rationale: str
    priority: str = "MEDIUM"
    advisory_only: bool = True
    requires_human_approval: bool = True


class InvestigationNarrative(BaseModel):
    headline: str
    summary: str
    why_suspicious: str
    uncertainty_notes: list[str] = Field(default_factory=list)
    generated_by: Literal["deterministic", "llm"] = "deterministic"


class InvestigationBundle(BaseModel):
    incident_id: UUID
    session_id: UUID | None = None
    merchant_id: UUID
    focus: str | None = None
    risk_score: float = Field(ge=0.0, le=100.0)
    trust_level: str
    trigger_reason: str
    incident_status: str
    evidence_counts: dict[str, int] = Field(default_factory=dict)
    findings: list[InvestigationFinding] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    recommendations: list[InvestigationRecommendation] = Field(default_factory=list)
    narrative: InvestigationNarrative
    redaction_applied: bool = True
    ai_used: bool = False
    model_name: str | None = None
    limitations: list[str] = Field(default_factory=list)


class InvestigationResponse(BaseModel):
    investigation_id: UUID
    incident_id: UUID
    session_id: UUID | None = None
    merchant_id: UUID
    status: InvestigationStatus
    ai_used: bool
    model_name: str | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    bundle: InvestigationBundle


class InvestigationListResponse(BaseModel):
    items: list[InvestigationResponse]
    total: int
    page: int
    page_size: int
