from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.analytics import AnalyticsOverviewResponse
from app.services.analytics_service import build_overview

router = APIRouter(prefix="/analytics", tags=["Operations Analytics"])

MAX_RANGE = timedelta(days=366)


@router.get(
    "/overview",
    response_model=AnalyticsOverviewResponse,
    summary="Operational overview metrics",
    description=(
        "Aggregates a complete, bounded record set for the authenticated merchant. "
        "The response is flagged when the range exceeds the server scan cap; "
        "client-side metrics are never derived from a single paginated page."
    ),
)
def analytics_overview(
    start: datetime | None = Query(None, description="Inclusive range start"),
    end: datetime | None = Query(None, description="Inclusive range end"),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AnalyticsOverviewResponse:
    now = datetime.now(timezone.utc)
    finish = end or now
    begin = start or (finish - timedelta(hours=24))
    if finish - begin > MAX_RANGE:
        begin = finish - MAX_RANGE
    if finish <= begin:
        finish = begin + timedelta(hours=1)
    return build_overview(db, principal, begin, finish)
