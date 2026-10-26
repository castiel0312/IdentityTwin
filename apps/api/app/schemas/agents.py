"""Read models for the agent registry, grants and audit trail."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.payout_queries import PayoutListItem


class AgentGrantView(BaseModel):
    grant_id: UUID
    agent_id: UUID
    merchant_id: UUID
    user_id: UUID
    session_id: UUID | None = None
    scopes: list[str] = Field(default_factory=list)
    max_amount: float | None = None
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None
    status: str


class AgentListItem(BaseModel):
    agent_id: UUID
    merchant_id: UUID
    display_name: str
    agent_type: str
    vendor: str | None = None
    scopes: list[str] = Field(default_factory=list)
    status: str
    is_active: bool
    max_payout_amount: float | None = None
    description: str | None = None
    active_grants: int = 0
    total_grants: int = 0
    audit_attempts: int = 0
    last_activity_at: datetime | None = None


class AgentListResponse(BaseModel):
    items: list[AgentListItem]
    total: int
    page: int
    page_size: int


class AgentAuditItem(BaseModel):
    audit_id: UUID
    agent_id: UUID
    agent_display_name: str | None = None
    grant_id: UUID | None = None
    session_id: UUID | None = None
    payout_id: UUID | None = None
    idempotency_key: str
    recipient_email: str
    amount: float
    currency: str
    status: str
    outcome: str | None = None
    agent_context: dict = Field(default_factory=dict)
    created_at: datetime


class AgentAuditListResponse(BaseModel):
    items: list[AgentAuditItem]
    total: int
    page: int
    page_size: int


class AgentDetailResponse(BaseModel):
    agent: AgentListItem
    grants: list[AgentGrantView] = Field(default_factory=list)
    recent_audit: list[AgentAuditItem] = Field(default_factory=list)
    recent_payouts: list[PayoutListItem] = Field(default_factory=list)


class AgentErrorDefinition(BaseModel):
    code: str
    http_status: int
    title: str
    explanation: str
    remediation: str


class AgentErrorCatalogResponse(BaseModel):
    errors: list[AgentErrorDefinition] = Field(default_factory=list)
