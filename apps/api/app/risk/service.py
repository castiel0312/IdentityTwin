import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.session import SessionRecord
from app.risk.schemas import RiskEvaluationRequest, RiskEvaluationResult
from app.schemas.sessions import TrustLevel


class IRiskEngineService(Protocol):
    """Protocol for risk engine implementations. Teammate (Risk Intelligence) will implement their full behavioral model here."""

    def evaluate(
        self, db: Session, session: SessionRecord, request: RiskEvaluationRequest
    ) -> RiskEvaluationResult: ...


class DeterministicRiskEngineService:
    """
    Foundational deterministic risk engine implementation.

    IMPORTANT ARCHITECTURAL NOTE:
    A risk score of 0.0 is an initial baseline default for clean sessions,
    NOT evidence that a real identity has been assessed or verified.
    """

    def evaluate(
        self, db: Session, session: SessionRecord, request: RiskEvaluationRequest
    ) -> RiskEvaluationResult:
        now = datetime.now(timezone.utc)
        signals = {}
        reason_codes = []

        # Inherit session baseline or explicitly evaluate
        raw_trust = session.trust_level.upper() if session.trust_level else "NORMAL"
        valid_levels = {t.value for t in TrustLevel}
        if raw_trust not in valid_levels:
            # Fail-closed: invalid or corrupted trust level must never fall back to NORMAL
            score = 100.0
            signals["INVALID_CORRUPTED_TRUST_STATE"] = 100.0
            reason_codes.append("CORRUPTED_TRUST_STATE_FAIL_CLOSED")
            evaluated_level = TrustLevel.ISOLATED
        elif raw_trust == TrustLevel.ISOLATED.value:
            score = max(float(session.risk_score or 90.0), 90.0)
            signals["PREVIOUS_SESSION_ISOLATION"] = score
            reason_codes.append("SESSION_PREVIOUSLY_ISOLATED")
            evaluated_level = TrustLevel.ISOLATED
        elif raw_trust == TrustLevel.DECOY.value:
            score = max(float(session.risk_score or 75.0), 75.0)
            signals["HONEY_ENVIRONMENT_FLAGGED"] = score
            reason_codes.append("DECOY_BEHAVIORAL_MATCH")
            evaluated_level = TrustLevel.DECOY
        elif raw_trust == TrustLevel.RESTRICTED.value:
            score = max(float(session.risk_score or 60.0), 60.0)
            signals["STEP_UP_CHALLENGE_PENDING"] = score
            reason_codes.append("RESTRICTED_STEP_UP_REQUIRED")
            evaluated_level = TrustLevel.RESTRICTED
        else:
            # Baseline normal session
            score = max(float(session.risk_score or 0.0), settings.RISK_BASELINE_SCORE)
            if request.amount > 10000.0:
                score += 30.0
                signals["HIGH_VALUE_TRANSACTION"] = 30.0
                reason_codes.append("HIGH_VALUE_THRESHOLD_EXCEEDED")
            else:
                signals["BASELINE_ACTIVITY"] = 0.0
                reason_codes.append("BASELINE_NORMAL_OPERATION")

            if score >= settings.RISK_THRESHOLD_ISOLATED:
                evaluated_level = TrustLevel.ISOLATED
            elif score >= settings.RISK_THRESHOLD_RESTRICTED:
                evaluated_level = TrustLevel.RESTRICTED
            else:
                evaluated_level = TrustLevel.NORMAL

        return RiskEvaluationResult(
            decision_id=uuid.uuid4(),
            session_id=session.session_id,
            risk_score=score,
            evaluated_trust_level=evaluated_level,
            risk_signals=signals,
            reason_codes=reason_codes,
            evaluated_at=now,
        )


# Global default instance (can be overridden via dependency injection)
default_risk_engine = DeterministicRiskEngineService()


def get_risk_engine() -> IRiskEngineService:
    return default_risk_engine
