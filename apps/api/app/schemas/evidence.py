"""Evidence seal read projections.

Hash-chain verification proves consistency with the available chain and the
persisted checkpoint. It does not prove that a database administrator could not
rewrite the database; callers must not overstate what the check establishes.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceSealSummary(BaseModel):
    seal_id: UUID
    incident_id: UUID
    incident_title: str
    incident_status: str
    session_id: UUID
    merchant_id: UUID
    start_seq: int
    end_seq: int
    head_hash: str
    sealed_at: datetime


class EvidenceSealListResponse(BaseModel):
    items: list[EvidenceSealSummary]
    total: int
    page: int
    page_size: int
    chain_head_hash: str | None = None
    chain_checkpoint_seq: int | None = None


class EvidenceEntryView(BaseModel):
    seq: int
    event_ref: str
    payload_hash: str
    prev_hash: str
    hash: str
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class SealVerificationView(BaseModel):
    scope: str = "seal_range"
    valid: bool
    checked: int
    reason: str | None = None
    head_matches: bool
    first_broken_seq: int | None = None


class EvidenceSealDetailResponse(BaseModel):
    seal: EvidenceSealSummary
    entries: list[EvidenceEntryView] = Field(default_factory=list)
    seal_verification: SealVerificationView
    limitations: list[str] = Field(default_factory=list)
