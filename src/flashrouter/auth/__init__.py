"""Gateway API-key authentication backed by the gateway_keys table."""

from __future__ import annotations

import secrets

from fastapi import Request

from flashrouter.config import Settings, is_configured
from flashrouter.errors import authentication_error, permission_error


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


async def require_gateway_key(request: Request) -> str | None:
    """Authenticate a bearer token against the gateway_keys table.

    Returns the matched gateway key id, or None when the gateway is not yet
    configured (setup mode, no auth enforced). Raises 401 for missing or
    invalid keys and 403 for disabled keys.
    """
    settings = get_settings(request)
    if not is_configured(settings):
        return None

    authorization = request.headers.get("authorization")
    if not authorization:
        raise authentication_error("Missing gateway API key")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise authentication_error("Invalid authorization header")
    token = parts[1].strip()
    if not token:
        raise authentication_error("Missing gateway API key")

    repo = request.app.state.request_repository
    if repo is None:
        raise authentication_error("Authentication storage is not available")

    key = await repo.get_gateway_key_by_secret(token)
    if key is None:
        # Fall back to the single legacy gateway API key from settings.
        legacy = settings.gateway_api_key()
        if legacy and secrets.compare_digest(token, legacy):
            return "default"
        raise authentication_error("Invalid gateway API key")

    if not key.get("enabled"):
        raise permission_error("Gateway key is disabled")

    await repo.update_gateway_key_last_used(key["id"])
    return key["id"]
