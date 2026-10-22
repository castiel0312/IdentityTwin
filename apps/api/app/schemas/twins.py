"""API schemas for the behavioural identity twin viewer."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.sessions import TrustLevel


class TwinDeviationResponse(BaseModel):
    """Deviation of a live session from the established twin baseline."""

    session_id: UUID
    risk_score: float
    trust_level: TrustLevel
    risk_signals: dict[str, float] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    is_new_device: bool = False
    is_new_location: bool = False
    is_unusual_hour: bool = False
    is_new_payee: bool = False
    is_large_payout: bool = False
    session_carried_forward: float = 0.0
    raw_points_sum: float = 0.0
    decay_points: float = 0.0


class TwinProfileResponse(BaseModel):
    """Behavioural baseline of one identity plus optional live deviation."""

    user_id: UUID
    merchant_id: UUID
    twin_id: UUID | None = None
    sample_count: int = 0
    is_provisional: bool = True
    confirmed_device_count: int = 0
    confirmed_location_count: int = 0
    confirmed_payee_count: int = 0
    pending_payee_count: int = 0
    active_hours: list[int] = Field(default_factory=list)
    hour_histogram: dict[str, int] = Field(default_factory=dict)
    total_amount: float = 0.0
    amount_count: int = 0
    device_fingerprints: list[str] = Field(default_factory=list)
    location_buckets: list[str] = Field(default_factory=list)
    last_updated_at: datetime | None = None
    deviation: TwinDeviationResponse | None = None
