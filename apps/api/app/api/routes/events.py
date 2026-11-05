from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import (
    AuthenticatedPrincipal,
    get_current_principal,
)
from app.db.session import get_db
from app.honey.events import _valid_cursor, stream_domain_events
from app.schemas.events import EventIngestRequest, EventIngestResponse
from app.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["Event Ingestion"])


@router.get(
    "/stream",
    response_class=StreamingResponse,
    summary="Stream retained domain events for the authenticated merchant",
)
async def stream_events(
    request: Request,
    after_event_id: str = Query(default="0"),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> StreamingResponse:
    if last_event_id is not None:
        after_event_id = last_event_id
    try:
        cursor = _valid_cursor(after_event_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    async def generate() -> AsyncGenerator[str, None]:
        async for event in stream_domain_events(
            request, principal.merchant_id, cursor
        ):
            yield event

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
