from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    incident_id: UUID
    merchant_id: UUID
    session_id: UUID | None = None
    title: str
    description: str
    severity: IncidentSeverity
    status: IncidentStatus
    risk_score: float = Field(ge=0.0, le=100.0)
    trigger_reason: str
    evidence_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None


class IncidentListResponse(BaseModel):
    items: list[IncidentResponse]
    total: int
    page: int
    page_size: int


class IncidentActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(
        None, max_length=500, description="Analyst review notes or justification"
    )
    resolution_reason: str | None = Field(
        None, max_length=255, description="Structured reason code or resolution tag"
    )


class IncidentActionResponse(BaseModel):
    incident_id: UUID
    action: str = Field(description="'approved' | 'resolved'")
    previous_status: IncidentStatus
    new_status: IncidentStatus
    analyst_id: UUID
    timestamp: datetime
    notes: str | None = None
    message: str = "Incident action recorded in audit log."
