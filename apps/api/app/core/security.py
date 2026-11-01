from collections.abc import Callable
from enum import Enum
from uuid import UUID
import time

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
import jwt
from jwt import PyJWKClient

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationRequiredException,
    InsufficientPermissionsException,
    OwnershipMismatchException,
)

security_scheme = HTTPBearer(auto_error=False)


class RoleEnum(str, Enum):
    MERCHANT = "merchant"
    ANALYST = "analyst"
    ADMIN = "admin"


class AuthenticatedPrincipal(BaseModel):
    """
    Authoritative server-side authenticated principal.
    Never populated from untrusted request body parameters.
    """

    user_id: UUID = Field(description="Unique identifier for the authenticated user")
    merchant_id: UUID = Field(description="Unique merchant account scope this user belongs to")
    role: RoleEnum = Field(
        default=RoleEnum.MERCHANT, description="Principal role for RBAC enforcement"
    )
    username: str = Field(default="user@example.com")
    auth_method: str = Field(default="dev_token")


# Well-known deterministic UUIDs for local development testing
DEV_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000001")
DEV_ANALYST_ID = UUID("00000000-0000-0000-0000-000000000002")
DEV_ALT_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000099")


ALLOWED_DEV_TOKENS = {
    settings.DEV_AUTH_TOKEN,
    "dev-merchant-token",
    "dev-analyst-token",
    "dev-other-merchant-token",
}


# JWKS Client for production JWT validation
_jwks_client: PyJWKClient | None = None
_jwks_cache_time: float = 0


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client, _jwks_cache_time
    now = time.time()
    if _jwks_client is None or (now - _jwks_cache_time) > settings.OIDC_CACHE_JWKS_SECONDS:
        jwks_url = settings.OIDC_JWKS_URL or f"{settings.OIDC_ISSUER_URL.rstrip('/')}/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
        _jwks_cache_time = now
    return _jwks_client


def _validate_jwt_token(token: str) -> dict:
    """Validate JWT token using JWKS and return decoded claims."""
    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=settings.OIDC_ALGORITHMS,
            audience=settings.OIDC_AUDIENCE,
            issuer=settings.OIDC_ISSUER_URL,
            options={"require": settings.OIDC_REQUIRED_CLAIMS},
        )
        return claims
    except jwt.ExpiredSignatureError:
        raise AuthenticationRequiredException("JWT token has expired.")
    except jwt.InvalidAudienceError:
        raise AuthenticationRequiredException("JWT token audience mismatch.")
    except jwt.InvalidIssuerError:
        raise AuthenticationRequiredException("JWT token issuer mismatch.")
    except jwt.InvalidTokenError as exc:
        raise AuthenticationRequiredException(f"Invalid JWT token: {exc}")


def _extract_principal_from_claims(claims: dict) -> AuthenticatedPrincipal:
    """Extract AuthenticatedPrincipal from validated JWT claims."""
    sub = claims.get("sub")
    email = claims.get("email")
    roles = claims.get(settings.OIDC_ROLE_CLAIM, [])
    merchant_id_str = claims.get(settings.OIDC_MERCHANT_CLAIM)

    if not sub or not email:
        raise AuthenticationRequiredException("JWT token missing required claims (sub, email).")

    # Determine role
    role = RoleEnum.MERCHANT
    if isinstance(roles, list) and "analyst" in roles:
        role = RoleEnum.ANALYST
    elif isinstance(roles, list) and "admin" in roles:
        role = RoleEnum.ADMIN

    # Parse merchant_id
    if not merchant_id_str:
        raise AuthenticationRequiredException(f"JWT token missing required claim: {settings.OIDC_MERCHANT_CLAIM}")
    try:
        merchant_id = UUID(merchant_id_str)
    except ValueError:
        raise AuthenticationRequiredException(f"Invalid merchant_id in JWT token: {merchant_id_str}")

    # Parse user_id from sub
    try:
        user_id = UUID(sub)
    except ValueError:
        # If sub is not a UUID, generate deterministic UUID from sub
        import hashlib
        sub_hash = hashlib.sha256(sub.encode()).hexdigest()[:32]
        user_id = UUID(sub_hash[:8] + "-" + sub_hash[8:12] + "-" + sub_hash[12:16] + "-" + sub_hash[16:20] + "-" + sub_hash[20:32])

    return AuthenticatedPrincipal(
        user_id=user_id,
        merchant_id=merchant_id,
        role=role,
        username=email,
        auth_method="oidc_jwt",
    )


def get_current_principal(
    bearer: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    x_dev_role: str | None = Header(None, alias="X-Dev-Role"),
    x_dev_merchant_id: str | None = Header(None, alias="X-Dev-Merchant-Id"),
    x_dev_user_id: str | None = Header(None, alias="X-Dev-User-Id"),
) -> AuthenticatedPrincipal:
    """
    Resolve and validate the caller's authoritative identity.
    In production, this extracts and validates standard OIDC / JWT bearer tokens.
    In local development, if ALLOW_DEV_AUTH is true, it strictly requires a valid dev token.
    Header overrides (X-Dev-*) are only permitted IF a valid dev token is presented.
    """
    token = bearer.credentials if bearer else None

    # Check for unauthenticated callers: token is strictly required
    if not token:
        raise AuthenticationRequiredException(
            message="Authentication credentials (Bearer token) are missing or invalid."
        )

    # Production authentication path
    if settings.ENVIRONMENT.lower() == "production":
        # Production JWT/OIDC validation using JWKS
        claims = _validate_jwt_token(token)
        return _extract_principal_from_claims(claims)

    # Development-only authentication mechanism
    if settings.ALLOW_DEV_AUTH and settings.ENVIRONMENT.lower() == "development":
        # Reject invalid/unknown tokens
        if token not in ALLOWED_DEV_TOKENS and not (
            token.startswith("dev-") or token == settings.DEV_AUTH_TOKEN
        ):
            raise AuthenticationRequiredException("Provided bearer token is expired or invalid.")

        # Determine baseline role from token
        if "analyst" in token.lower():
            role = RoleEnum.ANALYST
            merchant_id = DEV_MERCHANT_ID
            user_id = DEV_ANALYST_ID
            username = "analyst-dev@identitytwin.local"
        else:
            role = RoleEnum.MERCHANT
            merchant_id = DEV_MERCHANT_ID
            user_id = UUID("11111111-1111-1111-1111-111111111111")
            username = "merchant-dev@identitytwin.local"

        # Allow explicit header overrides in dev test suites only for authenticated dev callers
        if x_dev_role:
            try:
                role = RoleEnum(x_dev_role.lower())
            except ValueError:
                raise AuthenticationRequiredException(f"Invalid X-Dev-Role: {x_dev_role}") from None

        if x_dev_merchant_id:
            try:
                merchant_id = UUID(x_dev_merchant_id)
            except ValueError:
                raise AuthenticationRequiredException(
                    f"Invalid X-Dev-Merchant-Id UUID: {x_dev_merchant_id}"
                ) from None

        if x_dev_user_id:
            try:
                user_id = UUID(x_dev_user_id)
            except ValueError:
                raise AuthenticationRequiredException(
                    f"Invalid X-Dev-User-Id UUID: {x_dev_user_id}"
                ) from None

        return AuthenticatedPrincipal(
            user_id=user_id,
            merchant_id=merchant_id,
            role=role,
            username=username,
            auth_method="development_dev_token",
        )

    raise AuthenticationRequiredException("Authentication failed.")


def require_role(
    required_role: RoleEnum,
) -> Callable[[AuthenticatedPrincipal], AuthenticatedPrincipal]:
    """Dependency factory enforcing specific RBAC roles."""

    def role_checker(
        principal: AuthenticatedPrincipal = Depends(get_current_principal),
    ) -> AuthenticatedPrincipal:
        if principal.role != required_role and principal.role != RoleEnum.ADMIN:
            raise InsufficientPermissionsException(
                message=f"Action requires '{required_role.value}' role. Caller has role '{principal.role.value}'."
            )
        return principal

    return role_checker


def validate_merchant_scope(resource_merchant_id: UUID, principal: AuthenticatedPrincipal) -> None:
    """Ensure principal can only access resources belonging to their merchant account."""
    # Analysts can review incidents across merchants if explicitly granted or within scope
    if principal.merchant_id != resource_merchant_id:
        raise OwnershipMismatchException(
            message="Access denied: Resource belongs to a different merchant domain."
        )
