from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.events import EventIngestRequest, EventIngestResponse
from app.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["Event Ingestion"])


@router.post(
    "",
    response_model=EventIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest behavioral or security event",
    description="Ingests user telemetry, security, and behavioral telemetry bounded by session ownership.",
)
def ingest_event(
    request: EventIngestRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> EventIngestResponse:
    service = EventService(db)
    return service.ingest_event(request=request, principal=principal)
