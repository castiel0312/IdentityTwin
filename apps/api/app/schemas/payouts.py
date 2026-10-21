from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.sessions import TrustLevel


class GatewayAction(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_STEP_UP = "REQUIRE_STEP_UP"
    DECOY_FORWARD = "DECOY_FORWARD"
    BLOCK = "BLOCK"


class RoutingDestination(str, Enum):
    PROVIDER_PAYPAL = "PROVIDER_PAYPAL"
    PROVIDER_MOCK = "PROVIDER_MOCK"
    RESTRICTED_REJECT = "RESTRICTED_REJECT"
    DECOY_HONEY = "DECOY_HONEY"
    ISOLATED_BLOCK = "ISOLATED_BLOCK"


class PayoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID = Field(description="Active session initiating the payout")
    recipient_email: str = Field(
        min_length=5, max_length=255, description="Payout recipient email address"
    )
    amount: float = Field(
        gt=0.0, le=100000.0, description="Payout amount (must be positive, maximum 100,000.00)"
    )
    currency: str = Field(
        default="USD", min_length=3, max_length=3, description="ISO-4217 3-letter currency code"
    )
    reference_note: str | None = Field(
        None, max_length=255, description="Business reference or description"
    )
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        description="Unique caller-supplied client idempotency key to prevent double payouts",
    )
    step_up_token: str | None = Field(
        default=None,
        max_length=255,
        description="Optional verification token satisfying step-up challenge for restricted sessions",
    )

    @field_validator("recipient_email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid recipient email format")
        return v.strip().lower()

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        return v.upper()


class PayoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payout_id: UUID
    decision_id: UUID
    session_id: UUID
    status: str = Field(description="'completed' | 'rejected' | 'decoy_completed' | 'blocked'")
    trust_level: TrustLevel
    action: GatewayAction
    routing_destination: RoutingDestination
    risk_score: float = Field(ge=0.0, le=100.0)
    reason_codes: list[str]
    provider_reference: str | None = Field(
        None,
        description="Transaction reference returned by provider adapter (synthetic for mock)",
    )
    amount: float
    currency: str
    recipient_email: str
    created_at: datetime
    is_duplicate: bool = Field(
        default=False, description="True if response was served from idempotency cache"
    )
