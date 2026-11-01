import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.router import api_v1_router, health_router
from app.core.config import settings
from app.core.exceptions import IdentityTwinException, identitytwin_exception_handler
from app.db.session import init_db
from app.gateway.ratelimit import configure_default_limits, rate_limiter
from app.gateway.reconciliation_worker import ReconciliationWorker
from app.gateway.service import create_gateway_service
from app.honey.api import provider_router
from app.honey.api import router as honey_router

# Configure structured logging without sensitive payment credentials or auth tokens
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "logger":"%(name)s", "message":"%(message)s"}',
)
logger = logging.getLogger("identitytwin.api")

# Background reconciliation worker (started with the application, stopped on
# shutdown). One worker instance per API process.
reconciliation_worker: ReconciliationWorker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle management."""
    logger.info("Initializing IdentityTwin Trust Gateway API...")
    # Initialize DB tables for rapid local development/testing fallback
    init_db()
    # Configure default rate limits
    configure_default_limits()

    # Start the background reconciliation worker.
    global reconciliation_worker
    reconciliation_worker = ReconciliationWorker(
        gateway_service=create_gateway_service(),
    )
    await reconciliation_worker.start()

    logger.info(f"IdentityTwin API initialized in {settings.ENVIRONMENT} mode.")
    yield
    logger.info("Shutting down IdentityTwin API...")
    if reconciliation_worker is not None:
        await reconciliation_worker.stop()


def create_application() -> FastAPI:
    """Factory creating and configuring the FastAPI instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "Behavioral identity and trust gateway for merchant payment operations. "
            "Enforces centralized risk assessment, policy-driven payout routing, "
            "and secure incident management."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    @app.get("/", include_in_schema=False)
    def get_root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    # 1. CORS Configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
    )

    # 2. Rate Limiting Middleware
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        # Skip rate limiting for health checks and docs
        if request.url.path in ("/health", "/ready", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        # Skip rate limiting for test client (TestClient uses "testclient" as IP)
        # and in development environment for local testing
        if client_ip == "testclient" or settings.ENVIRONMENT.lower() == "development":
            return await call_next(request)

        # Get merchant_id from authenticated principal if available
        merchant_id = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            # We can't easily get the principal here without duplicating auth logic
            # Rate limiting will be per-IP for now, with per-merchant limits
            # enforced at the gateway service level for payouts
            pass

        # Check global IP rate limit
        ip_allowed, ip_headers = rate_limiter.check_limit(f"ip:global:{client_ip}")
        if not ip_allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests from this IP",
                    }
                },
                headers=ip_headers,
            )

        # Check auth-specific rate limit
        if request.url.path.startswith("/v1/") and request.method == "POST":
            auth_allowed, auth_headers = rate_limiter.check_limit(f"ip:auth:{client_ip}")
            if not auth_allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": "Too many authentication attempts",
                        }
                    },
                    headers=auth_headers,
                )

        response = await call_next(request)

        # Add rate limit headers to response
        for key, value in ip_headers.items():
            response.headers[key] = value

        return response

    # 3. Structured Request Logging Middleware (Sanitized: NO secrets or payment credentials logged)
    @app.middleware("http")
    async def audit_logging_middleware(request: Request, call_next):
        start_time = time.time()
        # Safe request metadata (never logging Authorization headers or request body payloads)
        method = request.method
        url_path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        # Log summary without sensitive request/response body contents
        logger.info(
            f"HTTP {method} {url_path} - status={response.status_code} duration={duration_ms}ms ip={client_ip}"
        )
        return response

    # 3. Exception Handlers
    app.add_exception_handler(IdentityTwinException, identitytwin_exception_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Format Pydantic validation errors consistently
        error_details = []
        for error in exc.errors():
            loc = " -> ".join([str(part) for part in error.get("loc", [])])
            msg = error.get("msg", "Invalid value")
            error_details.append({"location": loc, "issue": msg})

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request payload failed structural validation constraints.",
                    "details": {"validation_errors": error_details},
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled server error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected server error occurred.",
                    "details": {},
                }
            },
        )

    # 4. Mount Routers
    # Liveness and readiness probes directly accessible at /health and /ready
    app.include_router(health_router)
    # Versioned API routes mounted under /v1 prefix
    app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)
    app.include_router(honey_router, prefix=settings.API_V1_PREFIX)
    app.include_router(provider_router)

    return app


app = create_application()
