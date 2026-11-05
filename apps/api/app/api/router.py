from fastapi import APIRouter

from app.api.routes.agentic import router as agentic_router
from app.api.routes.agents import router as agents_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.events import router as events_router
from app.api.routes.evidence import router as evidence_router
from app.api.routes.health import router as health_router
from app.api.routes.honey_operator import router as honey_operator_router
from app.api.routes.incidents import router as incidents_router
from app.api.routes.intent import router as intent_router
from app.api.routes.investigations import router as investigations_router
from app.api.routes.payouts import router as payouts_router
from app.api.routes.reconciliation import router as reconciliation_router
from app.api.routes.risk import router as risk_router
from app.api.routes.sessions import router as sessions_router
from app.api.routes.simulation import router as simulation_router
from app.api.routes.stubs import router as stubs_router
from app.api.routes.system import router as system_router
from app.api.routes.twin import router as twin_router
from app.api.routes.vaccination import router as vaccination_router
from app.api.routes.webhooks import router as webhooks_router

api_v1_router = APIRouter()

# Group v1 endpoints
api_v1_router.include_router(events_router)
api_v1_router.include_router(reconciliation_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(payouts_router)
api_v1_router.include_router(incidents_router)
api_v1_router.include_router(intent_router)
api_v1_router.include_router(investigations_router)
api_v1_router.include_router(webhooks_router)
api_v1_router.include_router(twin_router)
api_v1_router.include_router(stubs_router)
api_v1_router.include_router(agentic_router)
api_v1_router.include_router(evidence_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(system_router)
api_v1_router.include_router(agents_router)
api_v1_router.include_router(risk_router)
api_v1_router.include_router(honey_operator_router)
api_v1_router.include_router(simulation_router)
api_v1_router.include_router(vaccination_router)

__all__ = ["api_v1_router", "health_router"]
