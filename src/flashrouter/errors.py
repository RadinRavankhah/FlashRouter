"""OpenAI-style error envelopes."""

from __future__ import annotations

from typing import Any


class GatewayError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        error_type: str = "invalid_request_error",
        code: str | None = None,
        param: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.type = error_type
        self.code = code
        self.param = param
        self.headers = headers or {}


def error_body(
    message: str,
    *,
    error_type: str = "invalid_request_error",
    code: str | None = None,
    param: str | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"message": message, "type": error_type}
    if param is not None:
        error["param"] = param
    if code is not None:
        error["code"] = code
    return {"error": error}


def anthropic_error_type(status_code: int, error_type: str) -> str:
    """Map a gateway error onto an Anthropic API error type."""
    if status_code == 404:
        return "not_found_error"
    if status_code == 401:
        return "authentication_error"
    if status_code == 403:
        return "permission_error"
    if status_code == 429:
        return "rate_limit_error"
    if error_type in {
        "authentication_error",
        "permission_error",
        "invalid_request_error",
        "not_found_error",
        "rate_limit_error",
    }:
        return error_type
    if status_code >= 500 or error_type in {"server_error", "upstream_error"}:
        return "api_error"
    return "invalid_request_error"


def anthropic_error_body(
    message: str,
    *,
    status_code: int,
    error_type: str = "invalid_request_error",
) -> dict[str, Any]:
    return {
        "type": "error",
        "error": {
            "type": anthropic_error_type(status_code, error_type),
            "message": message,
        },
    }


def model_not_found(model: str) -> GatewayError:
    return GatewayError(
        404,
        f"Model '{model}' is not configured on this gateway",
        code="model_not_found",
        param="model",
    )


def unauthorized(message: str = "Missing or invalid API key") -> GatewayError:
    return GatewayError(401, message, error_type="authentication_error", code="invalid_api_key")


def forbidden(message: str = "This API key is disabled") -> GatewayError:
    return GatewayError(403, message, error_type="permission_error", code="key_disabled")


def bad_request(message: str, *, param: str | None = None) -> GatewayError:
    return GatewayError(400, message, param=param)


def no_available_upstream(model: str) -> GatewayError:
    return GatewayError(
        502,
        f"No healthy upstream could serve model '{model}'",
        error_type="server_error",
        code="no_upstream",
    )


def upstream_error(status: int, message: str) -> GatewayError:
    return GatewayError(
        status if status >= 400 else 502,
        message,
        error_type="upstream_error",
        code="upstream_error",
    )
