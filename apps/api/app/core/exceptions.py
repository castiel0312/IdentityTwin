from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse


class IdentityTwinException(Exception):
    """Base exception for all domain and security errors in IdentityTwin."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_SERVER_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class AuthenticationRequiredException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Authentication credentials required or invalid.",
        code: str = "AUTHENTICATION_REQUIRED",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_401_UNAUTHORIZED,
            details=details,
        )


class InsufficientPermissionsException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Principal lacks required role or permissions for this action.",
        code: str = "INSUFFICIENT_PERMISSIONS",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_403_FORBIDDEN,
            details=details,
        )


class OwnershipMismatchException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Resource does not belong to the authenticated session or merchant scope.",
        code: str = "OWNERSHIP_MISMATCH",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_403_FORBIDDEN,
            details=details,
        )


class EntityNotFoundException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Requested resource not found.",
        code: str = "RESOURCE_NOT_FOUND",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )


class PolicyViolationException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Action denied by Trust Gateway policy enforcement.",
        code: str = "POLICY_VIOLATION",
        status_code: int = status.HTTP_403_FORBIDDEN,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            details=details,
        )


class DuplicateRequestException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Duplicate request identified by idempotency key.",
        code: str = "DUPLICATE_REQUEST",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class InvalidTrustStateException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Invalid or tampered trust state transition.",
        code: str = "INVALID_TRUST_STATE",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )


class PayloadValidationException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Request payload failed validation constraints.",
        code: str = "VALIDATION_ERROR",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )


class PaymentProviderException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Payment provider execution error.",
        code: str = "PROVIDER_EXECUTION_ERROR",
        status_code: int = status.HTTP_502_BAD_GATEWAY,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            details=details,
        )


class ProviderTimeoutException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Payment provider request timed out.",
        code: str = "PROVIDER_TIMEOUT",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            details=details,
        )


class ProviderRateLimitException(IdentityTwinException):
    def __init__(
        self,
        message: str = "Payment provider rate limit exceeded.",
        code: str = "PROVIDER_RATE_LIMITED",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details=details,
        )


class InvalidWebhookSignatureException(IdentityTwinException):
    def __init__(
        self,
        message: str = "PayPal webhook cryptographic signature verification failed.",
        code: str = "INVALID_WEBHOOK_SIGNATURE",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )


async def identitytwin_exception_handler(
    request: Request, exc: IdentityTwinException
) -> JSONResponse:
    """Consistent JSON response format for all application domain exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )
