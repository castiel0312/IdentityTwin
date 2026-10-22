"""Database aware adapter for the deterministic behavioral twin risk engine.

The public contract of this module is unchanged:

* ``IRiskEngineService.evaluate(db, session, request) -> RiskEvaluationResult``
* ``DeterministicRiskEngineService``
* ``get_risk_engine()``

Only additive behaviour was introduced: the engine now consults and updates a
per identity behavioural twin and a per session risk ledger.
"""

import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.repositories.twin_repo import TwinRepository
from app.models.incident import IncidentRecord
from app.models.session import SessionRecord
from app.risk.engine import BehavioralTwinEngine
from app.risk.schemas import (
    RiskEvaluationRequest,
    RiskEvaluationResult,
    SessionRiskState,
    TwinSnapshot,
)
from app.schemas.sessions import SessionStatus, TrustLevel

# Incident states that keep a session under active investigation.
_OPEN_INCIDENT_STATES = ("OPEN", "UNDER_REVIEW")


class IRiskEngineService(Protocol):
    """Protocol for risk engine implementations."""

    def evaluate(
        self, db: Session, session: SessionRecord, request: RiskEvaluationRequest
    ) -> RiskEvaluationResult: ...


class DeterministicRiskEngineService:
    """Deterministic behavioural twin risk engine.

    IMPORTANT ARCHITECTURAL NOTE:
    A risk score of 0.0 is an initial baseline default for clean sessions,
    NOT evidence that a real identity has been assessed or verified.
    """

    def __init__(self, engine: BehavioralTwinEngine | None = None):
        self.engine = engine or BehavioralTwinEngine()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _has_open_incident(db: Session, session: SessionRecord) -> bool:
        stmt = select(IncidentRecord.incident_id).where(
            IncidentRecord.session_id == session.session_id,
            IncidentRecord.status.in_(_OPEN_INCIDENT_STATES),
        )
        return db.scalars(stmt).first() is not None

    @staticmethod
    def _fail_closed(session: SessionRecord, now: datetime) -> RiskEvaluationResult:
        """Corrupted trust state must never fall back to NORMAL."""
        return RiskEvaluationResult(
            decision_id=uuid.uuid4(),
            session_id=session.session_id,
            risk_score=100.0,
            evaluated_trust_level=TrustLevel.ISOLATED,
            risk_signals={"INVALID_CORRUPTED_TRUST_STATE": 100.0},
            reason_codes=["CORRUPTED_TRUST_STATE_FAIL_CLOSED"],
            evaluated_at=now,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def evaluate(
        self, db: Session, session: SessionRecord, request: RiskEvaluationRequest
    ) -> RiskEvaluationResult:
        now = datetime.now(timezone.utc)

        raw_trust = session.trust_level.upper() if session.trust_level else "NORMAL"
        valid_levels = {t.value for t in TrustLevel}
        if raw_trust not in valid_levels:
            return self._fail_closed(session, now)

        merchant_id = session.merchant_id
        user_id = session.user_id

        session_score = float(
            session.risk_score if session.risk_score is not None else settings.RISK_BASELINE_SCORE
        )
        session_active = session.status == SessionStatus.ACTIVE.value
        open_incident = self._has_open_incident(db, session)

        repo = TwinRepository(db)

        twin_record = repo.get_twin(merchant_id, user_id)
        snapshot = (
            repo.to_snapshot(twin_record)
            if twin_record
            else TwinSnapshot(merchant_id=merchant_id, user_id=user_id)
        )

        state_record = repo.get_session_state(session.session_id)
        state = (
            repo.to_state(state_record)
            if state_record
            else SessionRiskState(
                session_id=session.session_id,
                merchant_id=merchant_id,
                user_id=user_id,
            )
        )

        outcome = self.engine.evaluate(
            request,
            snapshot,
            state,
            session_score=session_score,
            now=now,
            open_incident=open_incident,
            session_active=session_active,
        )

        if outcome.twin_updated:
            repo.save_twin_snapshot(outcome.twin)
        repo.save_session_state(outcome.state)

        return outcome.result


# Global default instance (can be overridden via dependency injection)
default_risk_engine = DeterministicRiskEngineService()


def get_risk_engine() -> IRiskEngineService:
    return default_risk_engine
