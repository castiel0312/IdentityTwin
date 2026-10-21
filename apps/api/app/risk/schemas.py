import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sessions import TrustLevel


class RiskEvaluationRequest(BaseModel):
    session_id: UUID
    merchant_id: UUID
    user_id: UUID
    action_type: str = "payout"
    amount: float = 0.0
    recipient: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


class RiskEvaluationResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision_id: UUID = Field(default_factory=uuid.uuid4)
    session_id: UUID
    risk_score: float = Field(ge=0.0, le=100.0, description="Evaluated risk score (0-100 scale)")
    evaluated_trust_level: TrustLevel = Field(
        description="Evaluated trust level before policy rules are applied"
    )
    risk_signals: dict[str, float] = Field(
        default_factory=dict,
        description="Named behavioral and security risk signals contributing to the score",
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="Named explanation codes for the risk assessment",
    )
    evaluated_at: datetime
