from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import (
    EntityNotFoundException,
    OwnershipMismatchException,
    PolicyViolationException,
)
from app.core.security import AuthenticatedPrincipal
from app.db.repositories.event_repo import EventRepository
from app.db.repositories.session_repo import SessionRepository
from app.models.event import SecurityEvent
from app.schemas.events import EventIngestRequest, EventIngestResponse
from app.schemas.sessions import SessionStatus


class EventService:
    def __init__(self, db: Session):
        self.db = db
        self.event_repo = EventRepository(db)
        self.session_repo = SessionRepository(db)

    def ingest_event(
        self,
        request: EventIngestRequest,
        principal: AuthenticatedPrincipal,
    ) -> EventIngestResponse:
        # Validate session ownership
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

        now = datetime.now(timezone.utc)

        # Create SecurityEvent record
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
            processed_by_risk_engine=False,
        )

        persisted = self.event_repo.create(db_event)
        self.session_repo.update_activity(session.session_id)

        return EventIngestResponse(
            event_id=persisted.event_id,
            session_id=persisted.session_id,
            server_received_at=persisted.server_received_at,
            status="accepted",
            message="Security event accepted and scheduled for behavioral analysis.",
        )
