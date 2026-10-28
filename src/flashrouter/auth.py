"""Gateway API-key authentication."""

from __future__ import annotations

import secrets

from fastapi import Request

from flashrouter.config import Settings
from flashrouter.errors import authentication_error


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def verify_bearer_token(authorization: str | None, expected_key: str) -> bool:
    if not authorization:
        return False
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    token = parts[1].strip()
    if not token:
        return False
    return secrets.compare_digest(token, expected_key)


def require_gateway_key(request: Request) -> None:
    settings = get_settings(request)
    if not verify_bearer_token(
        request.headers.get("authorization"),
        settings.gateway_api_key(),
    ):
        raise authentication_error()
