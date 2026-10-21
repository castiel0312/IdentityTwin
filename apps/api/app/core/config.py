from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API metadata
    PROJECT_NAME: str = "IdentityTwin Trust Gateway API"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/v1"

    # Environment
    ENVIRONMENT: str = Field(
        default="development", description="development | staging | production"
    )

    # Development-only authentication toggle
    ALLOW_DEV_AUTH: bool = Field(
        default=True,
        description="Whether development-only authentication is permitted. Must be False in production.",
    )
    DEV_AUTH_TOKEN: str = Field(
        default="dev-secret-token-change-in-prod",
        description="Dev auth static bearer token for local integration testing.",
    )

    # Database
    DATABASE_URL: str = Field(
        default="sqlite:///./identitytwin_dev.db",
        description="SQLAlchemy database connection URI (SQLite default for quick local runs, PostgreSQL for production)",
    )

    # CORS
    CORS_ORIGINS: list[str] | str = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        description="Allowed CORS origins",
    )

    # Gateway Policy Thresholds (PRD: Normal 0-29, Restricted 30-59, Decoy 60-89, Isolated 90-100)
    RISK_THRESHOLD_RESTRICTED: float = Field(default=30.0, ge=0.0, le=100.0)
    RISK_THRESHOLD_DECOY: float = Field(default=60.0, ge=0.0, le=100.0)
    RISK_THRESHOLD_ISOLATED: float = Field(default=90.0, ge=0.0, le=100.0)
    RESTRICTED_PAYOUT_LIMIT: float = Field(
        default=500.0,
        gt=0.0,
        description="Maximum payout amount permitted for Restricted trust level without step-up challenge",
    )
    RISK_BASELINE_SCORE: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Baseline risk score. Explicitly documented as 0 baseline score, not proof of identity.",
    )

    # Payment provider adapter configuration
    PAYMENT_PROVIDER: str = Field(
        default="mock",
        description="Payment provider adapter selection: 'mock' or 'paypal_sandbox'",
    )

    # PayPal Sandbox Configuration
    PAYPAL_CLIENT_ID: str = Field(default="", description="PayPal REST App Client ID for Sandbox")
    PAYPAL_CLIENT_SECRET: str = Field(
        default="", description="PayPal REST App Client Secret for Sandbox"
    )
    PAYPAL_WEBHOOK_ID: str = Field(
        default="", description="PayPal Webhook ID for signature verification"
    )
    PAYPAL_BASE_URL: str = Field(
        default="https://api-m.sandbox.paypal.com",
        description="PayPal REST API Base URL (must be sandbox endpoint)",
    )
    PAYPAL_REQUEST_TIMEOUT: float = Field(
        default=10.0,
        gt=0.0,
        description="HTTP request timeout in seconds for PayPal API calls",
    )

    # Logging
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FORMAT: str = Field(default="json", description="json | text")

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        elif isinstance(v, list):
            return v
        return ["http://localhost:3000", "http://localhost:5173"]

    @model_validator(mode="after")
    def validate_production_guards(self) -> "Settings":
        if self.ENVIRONMENT.lower() == "production":
            if self.ALLOW_DEV_AUTH:
                raise ValueError(
                    "ALLOW_DEV_AUTH cannot be enabled when ENVIRONMENT is 'production'"
                )
            if "sqlite" in self.DATABASE_URL.lower():
                raise ValueError(
                    "SQLite cannot be used as the database in production. Use PostgreSQL."
                )
        return self


settings = Settings()
