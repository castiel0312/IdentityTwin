import ipaddress
import math
from collections import Counter
from urllib.parse import urlsplit

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# IdentityTwin is sandbox-only. The PayPal REST base URL is therefore
# restricted to an explicit allowlist of official PayPal Sandbox hosts: a
# misconfigured (or maliciously injected) value must never be able to redirect
# payouts to PayPal production or to an attacker controlled lookalike.
#
# The allowlist is exact-match. `api-m.sandbox.paypal.com` is the current
# official Sandbox REST host; the retired `api.sandbox.paypal.com` host is
# deliberately not accepted.
PAYPAL_SANDBOX_HOST = "api-m.sandbox.paypal.com"
PAYPAL_SANDBOX_BASE_URL = f"https://{PAYPAL_SANDBOX_HOST}"
PAYPAL_ALLOWED_SANDBOX_HOSTS = frozenset({PAYPAL_SANDBOX_HOST})

# Payment provider adapter selection. The set is exhaustive on purpose: an
# unknown value is a configuration error, never a silent fallback to the mock
# adapter (a typo must not hide which provider will execute payouts).
PAYMENT_PROVIDER_MOCK = "mock"
PAYMENT_PROVIDER_PAYPAL_SANDBOX = "paypal_sandbox"
ALLOWED_PAYMENT_PROVIDERS = frozenset({PAYMENT_PROVIDER_MOCK, PAYMENT_PROVIDER_PAYPAL_SANDBOX})

# Hosts that must never be used as the optional LLM narrative endpoint. The
# Investigator only sends redacted evidence, but a configurable outbound URL is
# still an SSRF surface. Literal private/link-local addresses are rejected; the
# remaining residual risk is DNS rebinding (see docs/ai-investigator.md).
_UNSAFE_LLM_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "instance-data",
    }
)
_UNSAFE_LLM_HOST_SUFFIXES = (".localhost", ".local", ".internal")

_ALLOWED_OIDC_ALGORITHMS = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "PS256",
        "PS384",
        "PS512",
        "ES256",
        "ES384",
        "ES512",
        "EdDSA",
    }
)


def is_safe_llm_base_url(value: str) -> bool:
    """Return True when an LLM base URL is https and not an internal target."""
    parts = urlsplit(value.strip())
    if (
        parts.scheme.lower() != "https"
        or parts.username is not None
        or parts.password is not None
        or not parts.hostname
    ):
        return False
    host = parts.hostname.lower().rstrip(".")
    if host in _UNSAFE_LLM_HOSTNAMES or host.endswith(_UNSAFE_LLM_HOST_SUFFIXES):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return address.is_global and not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def has_valid_canary_secret_entropy(secret: str) -> bool:
    value = secret.strip()
    if not has_valid_secret_entropy(value):
        return False

    return value != "dev-canary-secret-change-me"


def has_valid_secret_entropy(secret: str) -> bool:
    value = secret.strip()
    if len(value) < 32:
        return False

    counts = Counter(value)
    entropy = -sum(
        (count / len(value)) * math.log2(count / len(value)) for count in counts.values()
    )
    return entropy >= 3.5


def validate_paypal_base_url(value: str) -> str:
    """
    Validate and canonicalize the PayPal REST base URL.

    Only the official PayPal Sandbox origin is accepted. Rejected:

    * empty / whitespace-only values (missing configuration),
    * any scheme other than ``https`` (insecure or non-http transports),
    * URLs embedding user credentials (``user:pass@host``),
    * non-default ports,
    * any path, query string or fragment (the adapter appends API paths
      itself, so a prefixed URL would escape the intended endpoint),
    * production hosts, lookalike hosts, and every host that is not on the
      explicit Sandbox allowlist.

    Returns the canonical base URL (no trailing slash) so callers get a
    normalized value instead of the raw input.
    """
    if not isinstance(value, str):
        raise ValueError("PAYPAL_BASE_URL must be a string.")

    raw = value.strip()
    if not raw:
        raise ValueError(
            "PAYPAL_BASE_URL is empty. Set it to the official PayPal Sandbox host "
            f"({PAYPAL_SANDBOX_BASE_URL}) or leave it unset to use the default."
        )

    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"PAYPAL_BASE_URL is not a valid URL: {exc}") from None

    if parts.scheme.lower() != "https":
        raise ValueError(
            "PAYPAL_BASE_URL must use the https scheme; insecure and non-http schemes are rejected."
        )
    if parts.username is not None or parts.password is not None:
        raise ValueError("PAYPAL_BASE_URL must not embed user credentials.")
    if port not in (None, 443):
        raise ValueError(f"PAYPAL_BASE_URL must not use a non-standard port (got {port}).")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("PAYPAL_BASE_URL must be a bare origin with no path, query or fragment.")

    host = (parts.hostname or "").lower()
    if host not in PAYPAL_ALLOWED_SANDBOX_HOSTS:
        raise ValueError(
            f"PAYPAL_BASE_URL host '{host}' is not an approved PayPal Sandbox host. "
            "IdentityTwin is sandbox-only: production hosts and lookalike hosts are rejected. "
            f"Approved hosts: {sorted(PAYPAL_ALLOWED_SANDBOX_HOSTS)}"
        )

    return PAYPAL_SANDBOX_BASE_URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # Never echo configured values in rendered ValidationError messages:
        # startup configuration errors must not leak credentials into logs.
        hide_input_in_errors=True,
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
        default="",
        description="Dev auth static bearer token for local integration testing. Must be set explicitly.",
    )

    # Production OIDC/JWT Configuration
    OIDC_ISSUER_URL: str = Field(
        default="",
        description="OIDC issuer URL (e.g., https://tenant.auth0.com, https://tenant.okta.com). Required for production.",
    )
    OIDC_JWKS_URL: str = Field(
        default="",
        description="OIDC JWKS URL for public key retrieval. If not set, derived from issuer URL.",
    )
    OIDC_AUDIENCE: str = Field(
        default="identitytwin-api",
        description="Expected JWT audience claim.",
    )
    OIDC_ALGORITHMS: list[str] = Field(
        default=["RS256"],
        description="Allowed JWT signing algorithms.",
    )
    OIDC_REQUIRED_CLAIMS: list[str] = Field(
        default=["sub", "email", "roles"],
        description="Required JWT claims for authentication.",
    )
    OIDC_ROLE_CLAIM: str = Field(
        default="roles",
        description="JWT claim name containing user roles.",
    )
    OIDC_MERCHANT_CLAIM: str = Field(
        default="merchant_id",
        description="JWT claim name containing merchant ID.",
    )
    OIDC_CACHE_JWKS_SECONDS: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="JWKS cache TTL in seconds.",
    )
    CANARY_HMAC_SECRET: str = Field(
        default="",
        description="High-entropy HMAC secret used to derive honey canaries.",
    )
    EVIDENCE_HMAC_KEY: str = Field(
        default="",
        description="High-entropy HMAC key used to sign evidence chain checkpoints.",
    )

    # ------------------------------------------------------------------
    # Person 6: AI Investigator configuration.
    #
    # The Investigator is read-only and advisory. Deterministic analysis and
    # redaction always run. The LLM narrative is optional, disabled by default
    # and never allowed to influence risk scoring, trust levels or payment
    # routing.
    # ------------------------------------------------------------------
    AI_INVESTIGATION_ENABLED: bool = Field(
        default=True,
        description="Enable the read-only AI Investigator API and deterministic narrative.",
    )
    AI_LLM_ENABLED: bool = Field(
        default=False,
        description=(
            "Enable the optional LLM narrative. Disabled by default; deterministic "
            "fallback is always used when disabled or when the provider fails."
        ),
    )
    AI_LLM_BASE_URL: str = Field(
        default="",
        description="OpenAI-compatible base URL for the optional narrative provider.",
    )
    AI_LLM_API_KEY: str = Field(
        default="",
        description="API key for the optional narrative provider. Never sent to clients.",
    )
    AI_LLM_MODEL: str = Field(
        default="",
        description="Model name used for the optional narrative.",
    )
    AI_LLM_TIMEOUT: float = Field(
        default=10.0,
        gt=0.0,
        le=120.0,
        description="Timeout in seconds for the optional LLM narrative request.",
    )
    AI_LLM_MAX_INPUT_CHARS: int = Field(
        default=12000,
        ge=1000,
        le=100000,
        description=(
            "Structural cap on the redacted evidence JSON sent to the optional LLM. "
            "Oversized projections are reduced field-by-field, never by cutting JSON."
        ),
    )
    AI_LLM_MAX_RESPONSE_BYTES: int = Field(
        default=65536,
        ge=1024,
        le=1_048_576,
        description=(
            "Maximum provider response body accepted by the optional LLM narrators. "
            "Oversized responses are rejected before JSON parsing."
        ),
    )
    AI_INVESTIGATION_MAX_EVENTS: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Maximum redacted events included in an investigation bundle.",
    )
    INTENT_PROFILER_ENABLED: bool = Field(
        default=True,
        description=(
            "Enable creation of advisory Intent Profiler snapshots. Reads remain "
            "available for existing snapshots."
        ),
    )

    # Database
    DATABASE_URL: str = Field(
        default="sqlite:///./identitytwin_dev.db",
        description="SQLAlchemy database connection URI (SQLite default for quick local runs, PostgreSQL for production)",
    )
    HONEY_DB_URL: str = Field(
        default="",
        description="Dedicated connection URI for the honey schema; defaults to DATABASE_URL.",
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

    # ------------------------------------------------------------------
    # Behavioral Twin / Risk Intelligence configuration (Person 2).
    # Signal weights are contract-stable: they are asserted by the risk
    # acceptance suite and must not be silently re-tuned. Thresholds above
    # (RESTRICTED/DECOY/ISOLATED) remain the routing contract.
    # ------------------------------------------------------------------
    RISK_WEIGHT_NEW_DEVICE: float = Field(default=18.0, ge=0.0)
    RISK_WEIGHT_NEW_LOCATION: float = Field(default=14.0, ge=0.0)
    RISK_WEIGHT_UNUSUAL_TIME: float = Field(default=11.0, ge=0.0)
    RISK_WEIGHT_NEW_PAYEE: float = Field(default=16.0, ge=0.0)
    RISK_WEIGHT_LARGE_PAYOUT: float = Field(default=21.0, ge=0.0)
    RISK_WEIGHT_NEW_PAYEE_LARGE_PAYOUT: float = Field(default=9.0, ge=0.0)
    RISK_WEIGHT_PAYEE_ADD_THEN_PAYOUT: float = Field(default=9.0, ge=0.0)
    RISK_WEIGHT_CANARY_INTERACTION: float = Field(default=11.0, ge=0.0)

    RISK_MIN_SAMPLES: int = Field(
        default=10,
        ge=1,
        description="Observations required before a behavioral twin is considered established (non-provisional).",
    )
    RISK_PROVISIONAL_FACTOR: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Weight multiplier applied to newness signals while a twin is still provisional.",
    )
    RISK_LARGE_PAYOUT_THRESHOLD: float = Field(
        default=5000.0,
        gt=0.0,
        description="Absolute payout amount above which a transaction is treated as a large payout.",
    )
    RISK_LARGE_PAYOUT_RELATIVE_FACTOR: float = Field(
        default=3.0,
        gt=1.0,
        description=(
            "A payout is large when it exceeds the absolute threshold and is at least this "
            "multiple of the identity's own average payout. The relative check keeps "
            "merchants whose normal payouts are large from being permanently elevated; it "
            "is skipped while no usable amount baseline exists."
        ),
    )
    RISK_AMOUNT_BASELINE_MIN_SAMPLES: int = Field(
        default=1,
        ge=1,
        description="Number of observed payouts required before the average payout of an identity is used.",
    )
    RISK_ACTIVE_HOUR_FRACTION: float = Field(
        default=0.10,
        gt=0.0,
        le=1.0,
        description="Minimum share of baseline activity required for an hour to count as 'active'.",
    )
    RISK_MIN_HOUR_SAMPLES: int = Field(
        default=10,
        ge=1,
        description="Minimum number of observed events required before an hour-of-day baseline is usable.",
    )
    RISK_HOUR_CONFIRM_OBSERVATIONS: int = Field(
        default=2,
        ge=1,
        description="Observations required before an hour-of-day counts as established for an identity.",
    )
    RISK_HOUR_CONCENTRATION_MIN: float = Field(
        default=0.25,
        gt=0.0,
        le=1.0,
        description=(
            "Minimum share of the busiest hour for the hour-of-day model to apply to an "
            "identity. Identities that are active around the clock have no meaningful "
            "time-of-day baseline, so the hour signal stays switched off for them."
        ),
    )
    RISK_CONTEXT_CONFIRM_OBSERVATIONS: int = Field(
        default=2,
        ge=1,
        description="Observations required before a device, location or payee counts as known for an identity.",
    )
    RISK_SEQUENCE_WINDOW_SECONDS: int = Field(
        default=1800,
        ge=1,
        description="Time window used to correlate multi-event attack sequences within one session.",
    )
    RISK_DECAY_POINTS_PER_EVENT: float = Field(
        default=5.0,
        ge=0.0,
        description="Risk points removed per eligible benign event. Never applied to canary evidence.",
    )
    RISK_TIME_DECAY_ENABLED: bool = Field(
        default=False,
        description="Optional wall-clock decay of transient points. Disabled by default for determinism.",
    )
    RISK_DEFAULT_TIMEZONE: str = Field(
        default="Asia/Kolkata",
        description="Merchant-local timezone used for hour-of-day behavioural baselines.",
    )
    RISK_DEVICE_HASH_SALT: str = Field(
        default="identitytwin-device-salt-v1",
        description="Salt used to hash device fingerprints before they are persisted.",
    )
    RISK_MAX_TRACKED_DEVICES: int = Field(default=25, ge=1)
    RISK_MAX_TRACKED_LOCATIONS: int = Field(default=25, ge=1)
    RISK_MAX_TRACKED_PAYEES: int = Field(default=100, ge=1)
    RISK_MAX_EVENT_FINGERPRINTS: int = Field(default=200, ge=1)
    RISK_PAYEE_CONFIRM_OBSERVATIONS: int = Field(
        default=2,
        ge=1,
        description="Benign observations required before a payee is treated as part of the trusted baseline.",
    )
    RISK_PROTECTED_ACTIONS: str = Field(
        default="payout,payout.submit,payout.attempt,payee.added,transfer,wire,withdrawal",
        description="Comma separated actions whose sessions never receive behavioural decay.",
    )
    RISK_CANARY_IDENTIFIERS: str = Field(
        default="IT-CANARY-0001,IT-CANARY-0002",
        description="Comma separated canary/honeypot identifiers that force level 3 isolation.",
    )
    RISK_SYNTHETIC_SEED: int = Field(
        default=20260921,
        description="Deterministic seed used by the synthetic identity generator and calibration harness.",
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
        default=PAYPAL_SANDBOX_BASE_URL,
        validate_default=True,
        description=(
            "PayPal REST API Base URL. Sandbox-only: validated against the official "
            "PayPal Sandbox host allowlist at settings initialization."
        ),
    )
    PAYPAL_REQUEST_TIMEOUT: float = Field(
        default=10.0,
        gt=0.0,
        description="HTTP request timeout in seconds for PayPal API calls",
    )

    @field_validator("PAYPAL_BASE_URL", mode="after")
    @classmethod
    def validate_paypal_base_url_setting(cls, value: str) -> str:
        # Runs at Settings construction (i.e. application startup), before any
        # provider request can possibly be made. An invalid value aborts
        # startup instead of silently pointing payouts at a non-Sandbox host.
        return validate_paypal_base_url(value)

    # Payment provider adapter configuration.
    #
    # Deliberately declared after the PayPal credential fields: the validator
    # below reads them from ``ValidationInfo.data`` so that a credential
    # requirement failure is reported against this field only. A model-level
    # error would attach the whole settings dict (including secrets) to the
    # ValidationError.
    PAYMENT_PROVIDER: str = Field(
        default=PAYMENT_PROVIDER_MOCK,
        validate_default=True,
        description=(
            "Payment provider adapter selection. Exhaustive: 'mock' or "
            "'paypal_sandbox'. Unknown values abort startup."
        ),
    )

    # Production mock override: must be explicitly set to allow mock provider
    # in production. Never enabled automatically. Requires intentional product
    # owner authorization.
    PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE: bool = Field(
        default=False,
        description=(
            "Explicit override to permit PAYMENT_PROVIDER='mock' in production. "
            "Never enable automatically. Requires product owner authorization."
        ),
    )

    @field_validator("PAYMENT_PROVIDER", mode="before")
    @classmethod
    def validate_payment_provider(cls, value: object, info: ValidationInfo) -> str:
        # Normalize harmless spelling (surrounding whitespace / case) but
        # reject every value that is not on the exhaustive allowlist instead of
        # silently selecting a different provider.
        if not isinstance(value, str):
            raise ValueError(
                "PAYMENT_PROVIDER must be one of "
                f"{sorted(ALLOWED_PAYMENT_PROVIDERS)}; got a non-string value."
            )
        normalized = value.strip().lower()
        if normalized not in ALLOWED_PAYMENT_PROVIDERS:
            raise ValueError(
                f"PAYMENT_PROVIDER must be one of {sorted(ALLOWED_PAYMENT_PROVIDERS)}; "
                f"got '{value.strip()}'. Unknown values are rejected instead of "
                "silently falling back to the mock provider."
            )
        # The mock provider is self-contained, so the offline development
        # workflow never needs PayPal credentials. Selecting the live Sandbox
        # adapter without them is a startup configuration error: failing here
        # is better than discovering it on the first payout attempt.
        if normalized == PAYMENT_PROVIDER_PAYPAL_SANDBOX:
            missing = [
                name
                for name in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET")
                if not str(info.data.get(name) or "").strip()
            ]
            if missing:
                # Only the variable names are echoed; never the configured
                # values (or partial values).
                raise ValueError(
                    "PAYMENT_PROVIDER is 'paypal_sandbox' but required "
                    f"credentials are missing or blank: {', '.join(missing)}. "
                    "Set them in the environment (see .env.example) or use "
                    "PAYMENT_PROVIDER='mock' for the offline development workflow."
                )
        return normalized

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

    @field_validator("OIDC_ALGORITHMS", mode="before")
    @classmethod
    def validate_oidc_algorithms(cls, value: object) -> list[str]:
        if isinstance(value, str):
            algorithms = [
                item.strip() for item in value.replace(",", " ").split() if item.strip()
            ]
        elif isinstance(value, (list, tuple)):
            algorithms = [str(item).strip() for item in value if str(item).strip()]
        else:
            raise ValueError("OIDC_ALGORITHMS must be a list of JWT signing algorithms.")

        invalid = sorted(set(algorithms) - _ALLOWED_OIDC_ALGORITHMS)
        if not algorithms or invalid:
            raise ValueError(
                "OIDC_ALGORITHMS must contain only asymmetric signing algorithms "
                f"from {sorted(_ALLOWED_OIDC_ALGORITHMS)}; got invalid values: {invalid}."
            )
        return algorithms

    @model_validator(mode="after")
    def validate_production_guards(self) -> "Settings":
        if self.ENVIRONMENT.lower() == "production":
            if self.ALLOW_DEV_AUTH:
                raise ValueError(
                    "ALLOW_DEV_AUTH cannot be enabled when ENVIRONMENT is 'production'"
                )
            canary_secret = self.CANARY_HMAC_SECRET.strip()
            if not has_valid_canary_secret_entropy(canary_secret):
                raise ValueError(
                    "CANARY_HMAC_SECRET must be explicitly configured with at least "
                    "32 characters of sufficient complexity when ENVIRONMENT is 'production'."
                )
            if not has_valid_secret_entropy(self.EVIDENCE_HMAC_KEY):
                raise ValueError(
                    "EVIDENCE_HMAC_KEY must be explicitly configured with at least "
                    "32 characters of sufficient complexity when ENVIRONMENT is 'production'."
                )
            if "sqlite" in self.DATABASE_URL.lower():
                raise ValueError(
                    "SQLite cannot be used as the database in production. Use PostgreSQL."
                )
            if not self.OIDC_ISSUER_URL.strip():
                raise ValueError("OIDC_ISSUER_URL is required when ENVIRONMENT is 'production'")
            if not self.OIDC_AUDIENCE.strip():
                raise ValueError("OIDC_AUDIENCE is required when ENVIRONMENT is 'production'")
            for name in ("OIDC_ISSUER_URL", "OIDC_JWKS_URL"):
                configured = str(getattr(self, name) or "").strip()
                if not configured:
                    continue
                parts = urlsplit(configured)
                if (
                    parts.scheme.lower() != "https"
                    or not parts.hostname
                    or parts.username is not None
                    or parts.password is not None
                ):
                    raise ValueError(f"{name} must be an https URL without embedded credentials.")
            # Production must reject the mock provider by default. A separate,
            # strongly controlled override is required if the product owner
            # explicitly authorizes mock operation in production.
            if self.PAYMENT_PROVIDER == PAYMENT_PROVIDER_MOCK:
                if not getattr(self, "PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE", False):
                    raise ValueError(
                        "PAYMENT_PROVIDER='mock' is not permitted in production. "
                        "Use PAYMENT_PROVIDER='paypal_sandbox' or set the explicit "
                        "PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE flag."
                    )
            if (
                self.PAYMENT_PROVIDER == PAYMENT_PROVIDER_PAYPAL_SANDBOX
                and not self.PAYPAL_WEBHOOK_ID.strip()
            ):
                raise ValueError(
                    "PAYPAL_WEBHOOK_ID is required in production when "
                    "PAYMENT_PROVIDER='paypal_sandbox'."
                )

        if self.AI_LLM_ENABLED:
            missing = [
                name
                for name in ("AI_LLM_BASE_URL", "AI_LLM_API_KEY", "AI_LLM_MODEL")
                if not str(getattr(self, name) or "").strip()
            ]
            if missing:
                raise ValueError(
                    "AI_LLM_ENABLED=true requires explicit configuration for: "
                    f"{', '.join(missing)}. Leave AI_LLM_ENABLED=false to use only "
                    "the deterministic narrative."
                )
            if not is_safe_llm_base_url(self.AI_LLM_BASE_URL):
                raise ValueError(
                    "AI_LLM_BASE_URL must be a public https origin without embedded "
                    "credentials or private/loopback/link-local targets."
                )
        return self


settings = Settings()
