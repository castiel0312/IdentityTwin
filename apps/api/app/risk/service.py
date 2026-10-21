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
        signals: dict[str, float] = {}
        reason_codes: list[str] = []

        # Inherit session baseline
        raw_trust = session.trust_level.upper() if session.trust_level else "NORMAL"
        valid_levels = {t.value for t in TrustLevel}

        if raw_trust not in valid_levels:
            # Fail-closed: invalid or corrupted trust level must never fall back to NORMAL
            score = 100.0
            signals["INVALID_CORRUPTED_TRUST_STATE"] = 100.0
            reason_codes.append("CORRUPTED_TRUST_STATE_FAIL_CLOSED")
            return RiskEvaluationResult(
                decision_id=uuid.uuid4(),
                session_id=session.session_id,
                risk_score=score,
                evaluated_trust_level=TrustLevel.ISOLATED,
                risk_signals=signals,
                reason_codes=reason_codes,
                evaluated_at=now,
            )

        # Baseline score from current session or configuration
        base_score = float(
            session.risk_score if session.risk_score is not None else settings.RISK_BASELINE_SCORE
        )

        # 7. Canary interaction: +11 plus mandatory Level 3 override
        is_canary = (
            request.context.get("is_canary") is True
            or request.context.get("canary") is True
            or request.action_type in ("canary.trap", "canary_interaction", "canary_trigger")
        )
        if is_canary:
            signals["CANARY_INTERACTION"] = 11.0
            reason_codes.append("CANARY_INTERACTION_LEVEL_3_OVERRIDE")

        # 1. New device: +18
        device_id = request.context.get("device_id")
        if request.context.get("is_new_device") is True or (
            device_id and session.device_fingerprint and device_id != session.device_fingerprint
        ):
            signals["NEW_DEVICE"] = 18.0
            reason_codes.append("NEW_DEVICE_DETECTED")

        # 2. New location: +14
        ip = request.context.get("ip_address")
        if (
            request.context.get("is_new_location") is True
            or request.context.get("location_mismatch") is True
            or (ip and session.ip_address and ip != session.ip_address)
        ):
            signals["NEW_LOCATION"] = 14.0
            reason_codes.append("NEW_LOCATION_DETECTED")

        # 3. Unusual time: +11
        if (
            request.context.get("is_unusual_time") is True
            or request.context.get("unusual_hour") is True
        ):
            signals["UNUSUAL_TIME"] = 11.0
            reason_codes.append("UNUSUAL_TRANSACTION_TIME")

        # 4. New payee: +16
        is_new_payee = (
            request.context.get("is_new_payee") is True
            or request.context.get("new_payee") is True
            or request.context.get("new_recipient") is True
        )
        if is_new_payee:
            signals["NEW_PAYEE"] = 16.0
            reason_codes.append("NEW_PAYEE_DESTINATION")

        # 5. Large payout: +21
        is_large_payout = (
            request.amount > 5000.0
            or request.context.get("is_large_payout") is True
            or request.context.get("large_payout") is True
        )
        if is_large_payout:
            signals["LARGE_PAYOUT"] = 21.0
            reason_codes.append("LARGE_PAYOUT_THRESHOLD_EXCEEDED")

        # 6. Compound: New payee followed by a large payout: +9
        if is_new_payee and is_large_payout:
            signals["NEW_PAYEE_LARGE_PAYOUT"] = 9.0
            reason_codes.append("COMPOUND_NEW_PAYEE_AND_LARGE_PAYOUT")

        if not signals:
            signals["BASELINE_ACTIVITY"] = 0.0
            reason_codes.append("BASELINE_NORMAL_OPERATION")

        # Calculate final score capped at 100.0
        score = min(100.0, base_score + sum(signals.values()))

        # Determine trust level using PRD thresholds
        if is_canary:
            # Mandatory Level 3 override
            evaluated_level = TrustLevel.ISOLATED
            score = max(score, settings.RISK_THRESHOLD_ISOLATED)
        elif score >= settings.RISK_THRESHOLD_ISOLATED:
            evaluated_level = TrustLevel.ISOLATED
            reason_codes.append("SESSION_ISOLATION_THRESHOLD_REACHED")
        elif score >= settings.RISK_THRESHOLD_DECOY:
            evaluated_level = TrustLevel.DECOY
            reason_codes.append("DECOY_HONEY_ROUTING_THRESHOLD_REACHED")
        elif score >= settings.RISK_THRESHOLD_RESTRICTED:
            evaluated_level = TrustLevel.RESTRICTED
            reason_codes.append("RESTRICTED_STEP_UP_THRESHOLD_REACHED")
        else:
            evaluated_level = TrustLevel.NORMAL
            reason_codes.append("NORMAL_TRUST_ELIGIBLE")

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
