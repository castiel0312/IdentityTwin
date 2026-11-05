"""Security Vaccination API schemas.

Signatures carry only normalized behavioral patterns: event sequences, feature
flags, risk indicators, and hashed identifiers. They never contain passwords,
access tokens, PayPal credentials, raw customer financial data, or unnecessary
PII.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VaccinationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class VaccinationAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REVOKE = "revoke"


class VaccinationSignatureSummary(BaseModel):
    """Compact projection of a vaccination signature."""

    signature_id: UUID
    source_merchant_id: UUID
    version: int
    status: VaccinationStatus
    name: str
    description: str | None = None
    detection_confidence: float = Field(ge=0.0, le=100.0)
    evidence_refs: list[int] = Field(default_factory=list)
    created_by: UUID
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    revoked_by: UUID | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VaccinationSignatureResponse(VaccinationSignatureSummary):
    """Full signature detail, including the sanitized pattern definition."""

    signature_definition: dict[str, Any] = Field(default_factory=dict)
    match_count: int = 0


class VaccinationSignatureListResponse(BaseModel):
    items: list[VaccinationSignatureSummary]
    total: int
    page: int
    page_size: int


class VaccinationSignatureCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID = Field(description="Session that experienced the confirmed attack")
    name: str = Field(min_length=1, max_length=128, description="Human-readable signature name")
    description: str | None = Field(
        None, max_length=1024, description="Explanation of the detected attack pattern"
    )
    signature_definition: dict[str, Any] = Field(
        default_factory=dict,
        description="Normalized, reproducible behavioral attack pattern (sanitized: no secrets or PII)",
    )
    detection_confidence: float = Field(
        default=80.0,
        ge=0.0,
        le=100.0,
        description="Confidence that the pattern represents a real attack",
    )
    evidence_refs: list[int] = Field(
        default_factory=list,
        description="Evidence chain sequence numbers supporting this signature",
    )


class VaccinationSignatureActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(
        None, max_length=500, description="Analyst review notes or justification"
    )


class VaccinationSignatureActionResponse(BaseModel):
    signature_id: UUID
    action: str
    previous_status: VaccinationStatus
    new_status: VaccinationStatus
    analyst_id: UUID
    timestamp: datetime
    notes: str | None = None
    message: str = "Signature lifecycle transition recorded in audit evidence."


class VaccinationMatchResponse(BaseModel):
    """A recorded match between a merchant's events and an active signature."""

    match_id: UUID
    signature_id: UUID
    signature_name: str
    target_merchant_id: UUID
    session_id: UUID | None = None
    matched_at: datetime
    match_score: float
    match_reason: str
    matched_features: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[int] = Field(default_factory=list)
    risk_points: float

    model_config = ConfigDict(from_attributes=True)


class VaccinationMatchListResponse(BaseModel):
    items: list[VaccinationMatchResponse]
    total: int
    page: int
    page_size: int


class VaccinationEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    amount: float = Field(default=0.0, ge=0.0)
    recipient: str = Field(default="")
    action_type: str = Field(default="payout")
    event_type: str = Field(default="payout.execute")


class VaccinationMatchDetail(BaseModel):
    """Explainable result of evaluating a request against active signatures."""

    matched: bool
    signature_id: UUID | None = None
    signature_name: str | None = None
    match_score: float = 0.0
    match_reason: str = ""
    matched_features: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[int] = Field(default_factory=list)
    risk_points: float = 0.0


class VaccinationEvaluateResponse(BaseModel):
    session_id: UUID
    merchant_id: UUID
    match: VaccinationMatchDetail


class VaccinationCrossMerchantDemoStep(BaseModel):
    step: str
    merchant_id: UUID
    risk_score: float
    trust_level: str
    matched: bool
    signature_id: UUID | None = None
    match_reason: str | None = None


class VaccinationCrossMerchantDemoResponse(BaseModel):
    """Deterministic before/after vaccination demonstration for two merchants."""

    scenario: str
    merchant_a_signature_id: UUID | None = None
    merchant_a_signature_approved: bool
    merchant_b_before: VaccinationCrossMerchantDemoStep
    merchant_b_after: VaccinationCrossMerchantDemoStep
    earlier_detection: bool
    evidence_valid: bool
