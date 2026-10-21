import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_v1_router, health_router
from app.core.config import settings
from app.core.exceptions import IdentityTwinException, identitytwin_exception_handler
from app.db.session import init_db

# Configure structured logging without sensitive payment credentials or auth tokens
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "logger":"%(name)s", "message":"%(message)s"}',
)
logger = logging.getLogger("identitytwin.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle management."""
    logger.info("Initializing IdentityTwin Trust Gateway API...")
    # Initialize DB tables for rapid local development/testing fallback
    init_db()
    logger.info(f"IdentityTwin API initialized in {settings.ENVIRONMENT} mode.")
    yield
    logger.info("Shutting down IdentityTwin API...")


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

    # 1. CORS Configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
    )

    # 2. Structured Request Logging Middleware (Sanitized: NO secrets or payment credentials logged)
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

    return app


app = create_application()
