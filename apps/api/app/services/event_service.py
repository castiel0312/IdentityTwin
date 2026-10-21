import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import (
    EntityNotFoundException,
    OwnershipMismatchException,
    PolicyViolationException,
)
from app.core.security import AuthenticatedPrincipal
from app.db.repositories.event_repo import EventRepository
from app.db.repositories.incident_repo import IncidentRepository
from app.db.repositories.session_repo import SessionRepository
from app.models.event import SecurityEvent
from app.models.incident import IncidentRecord
from app.risk.schemas import RiskEvaluationRequest
from app.risk.service import IRiskEngineService, get_risk_engine
from app.schemas.events import EventIngestRequest, EventIngestResponse
from app.schemas.incidents import IncidentSeverity, IncidentStatus
from app.schemas.sessions import SessionStatus, TrustLevel


class EventService:
    def __init__(self, db: Session, risk_engine: IRiskEngineService | None = None):
        self.db = db
        self.event_repo = EventRepository(db)
        self.session_repo = SessionRepository(db)
        self.incident_repo = IncidentRepository(db)
        self.risk_engine = risk_engine or get_risk_engine()

    def ingest_event(
        self,
        request: EventIngestRequest,
        principal: AuthenticatedPrincipal,
    ) -> EventIngestResponse:
        # 1. Validate session exists and belongs to caller
        session = self.session_repo.get_by_id(request.session_id)
        if not session:
            raise EntityNotFoundException(
                message=f"Session '{request.session_id}' not found.",
                code="SESSION_NOT_FOUND",
            )

        if session.merchant_id != principal.merchant_id or session.user_id != principal.user_id:
            raise OwnershipMismatchException(
                message="Session does not belong to the authenticated principal.",
                code="SESSION_OWNERSHIP_MISMATCH",
            )

        if session.status != SessionStatus.ACTIVE.value:
            raise PolicyViolationException(
                message=f"Session is in '{session.status}' status and cannot ingest events.",
                code="INACTIVE_SESSION",
            )

        # 2. Check event idempotency to prevent double-counting on retries
        if request.idempotency_key:
            existing = self.event_repo.get_by_idempotency_key(
                merchant_id=principal.merchant_id,
                idempotency_key=request.idempotency_key,
            )
            if existing:
                return EventIngestResponse(
                    event_id=existing.event_id,
                    session_id=session.session_id,
                    server_received_at=existing.server_received_at,
                    status="duplicate",
                    message="Event already processed with this idempotency key. Risk was not double-counted.",
                    risk_score=session.risk_score,
                    trust_level=TrustLevel(session.trust_level)
                    if session.trust_level
                    else TrustLevel.NORMAL,
                    risk_signals={},
                    reason_codes=["EVENT_IDEMPOTENCY_DEDUPLICATED"],
                )

        now = datetime.now(timezone.utc)

        # 3. Extract behavioral features and evaluate risk
        context = dict(request.metadata)
        if request.device_id:
            context["device_id"] = request.device_id
        if request.ip_address:
            context["ip_address"] = request.ip_address
        context["event_type"] = request.event_type.value
        context["action"] = request.action

        risk_req = RiskEvaluationRequest(
            session_id=session.session_id,
            merchant_id=principal.merchant_id,
            user_id=principal.user_id,
            action_type=request.action,
            amount=float(request.metadata.get("amount", 0.0)),
            recipient=str(
                request.metadata.get("recipient_email", request.metadata.get("recipient", ""))
            ),
            context=context,
        )

        risk_result = self.risk_engine.evaluate(self.db, session, risk_req)

        # 4. Check for canary or isolation trigger
        if risk_result.evaluated_trust_level == TrustLevel.ISOLATED:
            # Terminate/revoke session and isolate
            session.status = SessionStatus.REVOKED.value
            # Record security incident for analyst review
            incident = IncidentRecord(
                incident_id=uuid.uuid4(),
                merchant_id=principal.merchant_id,
                session_id=session.session_id,
                title="Immediate Security Isolation Triggered",
                description=(
                    f"Session isolated due to critical risk evaluation (score={risk_result.risk_score}). "
                    f"Action: {request.action}"
                ),
                severity=IncidentSeverity.CRITICAL.value,
                status=IncidentStatus.OPEN.value,
                risk_score=risk_result.risk_score,
                trigger_reason=risk_result.reason_codes[0]
                if risk_result.reason_codes
                else "ANOMALY_ISOLATION",
                evidence_summary={
                    "event_type": request.event_type.value,
                    "action": request.action,
                    "risk_signals": risk_result.risk_signals,
                    "reason_codes": risk_result.reason_codes,
                    "metadata": request.metadata,
                },
            )
            self.incident_repo.create(incident)

        # 5. Update session trust state and activity
        self.session_repo.update_trust_state(
            session_id=session.session_id,
            trust_level=risk_result.evaluated_trust_level.value,
            risk_score=risk_result.risk_score,
        )

        # 6. Persist SecurityEvent record
        db_event = SecurityEvent(
            session_id=session.session_id,
            merchant_id=principal.merchant_id,
            user_id=principal.user_id,
            event_type=request.event_type.value,
            occurred_at=request.occurred_at,
            server_received_at=now,
            device_id=request.device_id,
            ip_address=request.ip_address,
            action=request.action,
            metadata_payload=request.metadata,
            idempotency_key=request.idempotency_key,
            processed_by_risk_engine=True,
        )
        persisted = self.event_repo.create(db_event)

        return EventIngestResponse(
            event_id=persisted.event_id,
            session_id=persisted.session_id,
            server_received_at=persisted.server_received_at,
            status="accepted",
            message="Event processed and risk evaluated successfully.",
            risk_score=risk_result.risk_score,
            trust_level=risk_result.evaluated_trust_level,
            risk_signals=risk_result.risk_signals,
            reason_codes=risk_result.reason_codes,
        )
