from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.sessions import TrustLevel


class EventType(str, Enum):
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    SESSION_HEARTBEAT = "session.heartbeat"
    BEHAVIORAL_KEYSTROKE = "behavioral.keystroke"
    BEHAVIORAL_MOUSE = "behavioral.mouse"
    NAVIGATION_PAGEVIEW = "navigation.pageview"
    PAYOUT_ATTEMPT = "payout.attempt"
    PAYOUT_SUBMIT = "payout.submit"
    SECURITY_MFA_CHALLENGE = "security.mfa_challenge"
    SECURITY_ANOMALY_DETECTED = "security.anomaly_detected"


class EventIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: EventType = Field(
        description="Standardized security or behavioral event classification"
    )
    session_id: UUID = Field(description="Authoritative session identifier")
    occurred_at: datetime = Field(description="Client event timestamp (ISO 8601 UTC)")
    device_id: str | None = Field(
        None, max_length=128, description="Device fingerprint or identifier"
    )
    ip_address: str | None = Field(
        None, max_length=45, description="Client IP address (IPv4 or IPv6)"
    )
    action: str = Field(min_length=1, max_length=64, description="Discrete user action name")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured, bounded event metadata (no arbitrary unbounded JSON)",
    )
    idempotency_key: str | None = Field(None, min_length=8, max_length=128)

    @field_validator("occurred_at")
    @classmethod
    def validate_timestamp(cls, v: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        # Ensure timezone-aware
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        # Check not > 10 minutes in the future (clock skew tolerance)
        diff_future = (v - now).total_seconds()
        if diff_future > 600:
            raise ValueError("Event occurred_at cannot be in the future")
        # Check not > 30 days in the past
        diff_past = (now - v).total_seconds()
        if diff_past > 30 * 86400:
            raise ValueError("Event occurred_at cannot be older than 30 days")
        return v

    @field_validator("metadata")
    @classmethod
    def validate_metadata_bounds(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > 25:
            raise ValueError("Metadata may not contain more than 25 keys")
        for key, val in v.items():
            if len(key) > 64:
                raise ValueError(f"Metadata key '{key}' exceeds 64 characters")
            # Only allow scalar types or small lists/dicts
            if isinstance(val, (str, int, float, bool)) or val is None:
                if isinstance(val, str) and len(val) > 1024:
                    raise ValueError(f"Metadata value for '{key}' exceeds 1024 characters")
            elif isinstance(val, (list, dict)):
                str_rep = str(val)
                if len(str_rep) > 2048:
                    raise ValueError(f"Complex metadata value for '{key}' exceeds 2048 bytes")
            else:
                raise ValueError(f"Unsupported metadata value type: {type(val)}")
        return v


class EventIngestResponse(BaseModel):
    event_id: UUID
    session_id: UUID
    server_received_at: datetime
    status: str = Field(default="accepted", description="'accepted' or 'duplicate'")
    message: str = "Event recorded successfully."
    risk_score: float | None = Field(
        default=None, description="Current cumulative session risk score"
    )
    trust_level: TrustLevel | None = Field(
        default=None, description="Authoritative session trust level"
    )
    risk_signals: dict[str, float] = Field(
        default_factory=dict, description="Named risk contributions from event"
    )
    reason_codes: list[str] = Field(
        default_factory=list, description="Explanatory decision reason codes"
    )
