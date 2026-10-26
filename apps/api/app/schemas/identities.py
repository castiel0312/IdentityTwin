"""Identity and behavioural twin read projections."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.sessions import SessionResponse


class TwinSummary(BaseModel):
    twin_id: UUID
    sample_count: int = 0
    is_provisional: bool = True
    confirmed_device_count: int = 0
    confirmed_location_count: int = 0
    confirmed_payee_count: int = 0
    pending_payee_count: int = 0
    active_hours: list[int] = Field(default_factory=list)
    amount_count: int = 0
    last_updated_at: datetime | None = None


class IdentityListItem(BaseModel):
    user_id: UUID
    merchant_id: UUID
    email: str
    role: str
    is_active: bool
    twin: TwinSummary | None = None
    sessions_total: int = 0
    active_sessions: int = 0
    max_risk_score: float = 0.0
    last_activity_at: datetime | None = None


class IdentityListResponse(BaseModel):
    items: list[IdentityListItem]
    total: int
    page: int
    page_size: int


class IdentityDetailResponse(BaseModel):
    identity: IdentityListItem
    sessions: list[SessionResponse] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
