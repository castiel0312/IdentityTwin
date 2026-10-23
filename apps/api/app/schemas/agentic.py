"""
Schemas for the internal agentic commerce adapter contract (Person 3).

No third-party agentic payment specification is implemented here. The shapes
below are an INTERNAL IdentityTwin contract between an AI agent (or the
merchant application embedding it) and the Trust Gateway. They are documented
in `docs/agentic-commerce.md`.

Design rules enforced by these schemas:

* The caller states WHICH agent is acting (`agent_id`) and WHICH delegation
  authorizes it (`authorization_grant_id`). Everything else about the agent
  (name, type, vendor, scopes, limits) is resolved server side from the
  registry, so an agent can never describe itself.
* No trust level, risk score, merchant id, user id or provider hint may be
  supplied by the caller: unknown fields are rejected outright.
* The idempotency key is mandatory and is preserved verbatim through
  normalization, so agent retries are deduplicated by the Trust Gateway.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.payouts import PayoutResponse


class AgentScope(str, Enum):
    """
    Capabilities an agent may hold.

    Scopes are additive and are only ever narrowed by the server: an agent
    must hold the scope in its registration AND in the presented grant.
    """

    PAYOUT_EXECUTE = "payout:execute"
    PAYOUT_READ = "payout:read"
    COMMERCE_PURCHASE = "commerce:purchase"


class AgenticCommerceRequest(BaseModel):
    """
    An AI agent initiated commerce / payout request.

    This is the inbound half of the internal adapter contract. It carries the
    agent reference, the authorization reference and the intended transaction.
    It carries no identity claim: merchant, user and session authority are
    resolved from the authenticated principal and the server side registry.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID = Field(description="Registered agent that initiates the request")
    authorization_grant_id: UUID = Field(
        description="Delegation grant issued to the agent for this merchant user"
    )
    session_id: UUID = Field(description="Merchant session the agent acts within")
    recipient_email: str = Field(
        min_length=5, max_length=255, description="Recipient of the agent initiated payment"
    )
    amount: float = Field(
        gt=0.0, le=100000.0, description="Amount to disburse (maximum 100,000.00)"
    )
    currency: str = Field(
        default="USD", min_length=3, max_length=3, description="ISO-4217 3-letter currency code"
    )
    reference_note: str | None = Field(
        None, max_length=255, description="Business reference or agent supplied note"
    )
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        description="Caller supplied idempotency key, preserved verbatim by the adapter",
    )
    step_up_token: str | None = Field(
        default=None,
        max_length=255,
        description="Optional step-up verification token for restricted sessions",
    )
    agent_intent: str | None = Field(
        default=None,
        max_length=255,
        description="Optional description of the agent intent, recorded for audit only",
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


class AgentIdentity(BaseModel):
    """
    Server resolved identity of the acting agent.

    Built exclusively from the agent registry, never from the request body.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: UUID
    display_name: str
    agent_type: str
    vendor: str | None = None
    scopes: list[str] = Field(default_factory=list)
    status: str


class AgentAuthorizationContext(BaseModel):
    """
    Server resolved authorization context of an agent initiated action.

    Describes the delegation that permitted the action: who delegated it, what
    it is scoped to, how long it is valid and which amount ceiling applies.
    """

    model_config = ConfigDict(frozen=True)

    grant_id: UUID
    agent_id: UUID
    merchant_id: UUID
    delegated_by_user_id: UUID
    session_id: UUID | None = None
    scopes: list[str] = Field(default_factory=list)
    max_amount: float | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None

    def as_audit_context(self) -> dict[str, object]:
        """Audit friendly projection (no credentials, no payment instruments)."""
        return {
            "grant_id": str(self.grant_id),
            "agent_id": str(self.agent_id),
            "merchant_id": str(self.merchant_id),
            "delegated_by_user_id": str(self.delegated_by_user_id),
            "session_id": str(self.session_id) if self.session_id else None,
            "scopes": list(self.scopes),
            "max_amount": self.max_amount,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class AgentAuthorizationDecision(BaseModel):
    """
    Result of the adapter authorization step.

    Bundles the server resolved agent identity with the authorization context
    that permitted the action.
    """

    model_config = ConfigDict(frozen=True)

    agent: AgentIdentity
    authorization: AgentAuthorizationContext


class AgenticCommerceResponse(PayoutResponse):
    """
    Trust Gateway outcome for an agent initiated request.

    The gateway response is preserved verbatim and the agent provenance is
    attached, so the caller can attribute the result to the acting agent.
    """

    model_config = ConfigDict(from_attributes=True)

    agent_id: UUID
    agent_display_name: str
    agent_type: str
    authorization_grant_id: UUID
    delegated_by_user_id: UUID
    agent_intent: str | None = None
