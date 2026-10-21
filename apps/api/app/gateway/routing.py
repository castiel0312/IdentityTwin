from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.payouts import GatewayAction, RoutingDestination
from app.schemas.sessions import TrustLevel


class GatewayRoutingDecision(BaseModel):
    """
    Authoritative server-side routing decision emitted by the Trust Gateway.
    Returned to callers and logged for audit and compliance.
    """

    model_config = ConfigDict(from_attributes=True)

    decision_id: UUID
    session_id: UUID
    risk_score: float = Field(ge=0.0, le=100.0, description="Evaluated risk score (0-100 scale)")
    trust_level: TrustLevel
    action: GatewayAction
    routing_destination: RoutingDestination
    reason_codes: list[str]
    timestamp: datetime
