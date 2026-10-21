from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TrustLevel(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    DECOY = "DECOY"
    ISOLATED = "ISOLATED"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    user_id: UUID
    merchant_id: UUID
    trust_level: TrustLevel
    risk_score: float = Field(ge=0.0, le=100.0, description="Evaluated risk score (0-100 scale)")
    status: SessionStatus
    device_fingerprint: str | None = None
    ip_address: str | None = None
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
    total: int
    page: int
    page_size: int


class SessionCreateRequest(BaseModel):
    """Client request to register a new user session."""

    model_config = ConfigDict(extra="forbid")

    device_fingerprint: str | None = Field(None, max_length=128)
    ip_address: str | None = Field(None, max_length=45)
    # Note: Client cannot set trust_level or risk_score! They are initialized server-side.


class StepUpChallengeCreateResponse(BaseModel):
    challenge_id: UUID
    session_id: UUID
    expires_at: datetime
    simulated_otp: str | None = Field(
        None, description="Simulated OTP code provided for local development and test environments"
    )


class StepUpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID = Field(description="ID of the issued step-up challenge")
    code: str = Field(min_length=4, max_length=16, description="One-time verification code")


class StepUpVerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID
    session_id: UUID
    status: str = "verified"
    step_up_token: str = Field(
        description="Single-use token authorizing restricted payout execution"
    )
    expires_at: datetime
