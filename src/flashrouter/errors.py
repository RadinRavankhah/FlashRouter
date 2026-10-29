"""OpenAI-compatible error types and response helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class GatewayError(Exception):
    status_code: int
    message: str
    type: str = "invalid_request_error"
    code: str | None = None
    param: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def error_body(
    message: str,
    *,
    error_type: str = "invalid_request_error",
    code: str | None = None,
    param: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "message": message,
            "type": error_type,
            "param": param,
            "code": code,
        }
    }


def authentication_error(message: str = "Invalid gateway API key") -> GatewayError:
    return GatewayError(
        status_code=401,
        message=message,
        type="authentication_error",
        code="invalid_api_key",
        headers={"WWW-Authenticate": "Bearer"},
    )


def permission_error(message: str = "Gateway key is disabled") -> GatewayError:
    return GatewayError(
        status_code=403,
        message=message,
        type="authentication_error",
        code="key_disabled",
        headers={"WWW-Authenticate": "Bearer"},
    )


def invalid_request(
    message: str,
    *,
    code: str = "invalid_request",
    param: str | None = None,
) -> GatewayError:
    return GatewayError(
        status_code=400,
        message=message,
        type="invalid_request_error",
        code=code,
        param=param,
    )


def upstream_connection_error(message: str) -> GatewayError:
    return GatewayError(
        status_code=502,
        message=message,
        type="upstream_error",
        code="upstream_connection_failed",
    )


def upstream_timeout_error(message: str = "Upstream request timed out") -> GatewayError:
    return GatewayError(
        status_code=504,
        message=message,
        type="upstream_error",
        code="upstream_timeout",
    )
