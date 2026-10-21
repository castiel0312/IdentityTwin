from datetime import datetime, timezone

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.db.session import check_db_ready

router = APIRouter(tags=["Health & Diagnostics"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    timestamp: datetime


class ReadyResponse(BaseModel):
    status: str
    database: str
    timestamp: datetime


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def get_liveness() -> HealthResponse:
    """Indicates that the API server process is alive and accepting connections."""
    return HealthResponse(
        status="ok",
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready", response_model=ReadyResponse, summary="Readiness probe")
def get_readiness(response: Response) -> ReadyResponse:
    """Verifies that all required backend dependencies (database) are operational."""
    db_ok = check_db_ready()
    now = datetime.now(timezone.utc)

    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(
            status="unavailable",
            database="unhealthy",
            timestamp=now,
        )

    return ReadyResponse(
        status="ready",
        database="connected",
        timestamp=now,
    )
