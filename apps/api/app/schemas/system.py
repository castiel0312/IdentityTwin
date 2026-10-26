"""System context and capability projection for the operator console."""

from uuid import UUID

from pydantic import BaseModel, Field


class PrincipalView(BaseModel):
    user_id: UUID
    merchant_id: UUID
    role: str
    username: str
    auth_method: str


class MerchantView(BaseModel):
    merchant_id: UUID
    name: str
    slug: str
    is_active: bool


class AuthContextView(BaseModel):
    mode: str = Field(description="development_dev_token | oidc_unconfigured")
    development_only: bool
    oidc_configured: bool
    limitations: list[str] = Field(default_factory=list)


class ProviderContextView(BaseModel):
    mode: str
    sandbox_only: bool
    webhook_verification_configured: bool
    notes: list[str] = Field(default_factory=list)


class ThresholdView(BaseModel):
    restricted: float
    decoy: float
    isolated: float
    restricted_payout_limit: float
    baseline_score: float


class RiskSignalWeight(BaseModel):
    name: str
    weight: float
    description: str


class RiskContextView(BaseModel):
    weights: list[RiskSignalWeight] = Field(default_factory=list)
    sequence_window_seconds: int
    min_samples: int
    provisional_factor: float
    decay_points_per_event: float
    default_timezone: str
    protected_actions: list[str] = Field(default_factory=list)


class CapabilityView(BaseModel):
    id: str
    name: str
    available: bool
    detail: str


class SystemContextResponse(BaseModel):
    principal: PrincipalView
    merchant: MerchantView | None = None
    environment: str
    auth: AuthContextView
    provider: ProviderContextView
    thresholds: ThresholdView
    risk: RiskContextView
    capabilities: list[CapabilityView] = Field(default_factory=list)
