"""JWT-based admin authentication (HS256, no extra dependency)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import Request

from flashrouter.config import Settings
from flashrouter.errors import GatewayError, authentication_error

JWT_ALGORITHM = "HS256"
JWT_TTL_SECONDS = 3600  # 1 hour


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _hmac_sha256(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def encode_admin_token(secret_key: str, *, ttl_seconds: int = JWT_TTL_SECONDS) -> str:
    now = int(time.time())
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": "admin",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode()) + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = _hmac_sha256(secret_key.encode(), signing_input.encode())
    return signing_input + "." + _b64url(signature)


def decode_admin_token(token: str, secret_key: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise authentication_error("Invalid token format") from None
    try:
        header = json.loads(_b64url_decode(parts[0]))
        payload = json.loads(_b64url_decode(parts[1]))
        signature = _b64url_decode(parts[2])
    except Exception as exc:
        raise authentication_error("Invalid token encoding") from exc

    if header.get("alg") != JWT_ALGORITHM:
        raise authentication_error("Unsupported token algorithm")

    signing_input = (parts[0] + "." + parts[1]).encode()
    expected = _hmac_sha256(secret_key.encode(), signing_input)
    if not hmac.compare_digest(signature, expected):
        raise authentication_error("Invalid token signature")

    now = int(time.time())
    if payload.get("exp", 0) <= now:
        raise authentication_error("Token expired")

    return payload


def get_admin_secret(settings: Settings) -> str:
    return settings.admin_secret_key()


def require_admin_token(request: Request) -> None:
    settings = get_settings(request)
    authorization = request.headers.get("authorization")
    if not authorization:
        raise authentication_error("Missing admin token")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise authentication_error("Invalid authorization header")
    token = parts[1].strip()
    if not token:
        raise authentication_error("Missing admin token")
    try:
        decode_admin_token(token, get_admin_secret(settings))
    except GatewayError:
        raise
    except Exception as exc:
        raise authentication_error("Invalid token") from exc


def get_settings(request: Request) -> Settings:
    return request.app.state.settings
