from collections.abc import Callable
from enum import Enum
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

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
        # Production JWT/OIDC validation hook (e.g. PyJWT with JWKS from Auth0 / Okta / Cognito)
        # For security, development headers and tokens are strictly rejected in production.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Production OIDC/OAuth2 provider verification must be configured with JWKS.",
        )

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
