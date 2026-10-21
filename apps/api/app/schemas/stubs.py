from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable error explanation")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Contextual error details and owner metadata"
    )


class StandardErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
