from fastapi import APIRouter

from app.api.routes.agentic import router as agentic_router
from app.api.routes.events import router as events_router
from app.api.routes.health import router as health_router
from app.api.routes.incidents import router as incidents_router
from app.api.routes.payouts import router as payouts_router
from app.api.routes.sessions import router as sessions_router
from app.api.routes.stubs import router as stubs_router
from app.api.routes.twin import router as twin_router
from app.api.routes.webhooks import router as webhooks_router

api_v1_router = APIRouter()

# Group v1 endpoints
api_v1_router.include_router(events_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(payouts_router)
api_v1_router.include_router(incidents_router)
api_v1_router.include_router(webhooks_router)
api_v1_router.include_router(twin_router)
api_v1_router.include_router(stubs_router)
api_v1_router.include_router(agentic_router)

__all__ = ["api_v1_router", "health_router"]
