"""Unit tests for JWT admin authentication."""

from __future__ import annotations

import pytest

from flashrouter.auth.jwt import decode_admin_token, encode_admin_token
from flashrouter.errors import GatewayError


@pytest.mark.anyio
async def test_encode_decode_admin_token_roundtrip() -> None:
    token = encode_admin_token("test-secret-key-123")
    payload = decode_admin_token(token, "test-secret-key-123")
    assert payload["sub"] == "admin"
    assert "iat" in payload
    assert "exp" in payload


@pytest.mark.anyio
async def test_wrong_secret_rejected() -> None:
    token = encode_admin_token("secret-a")
    with pytest.raises(GatewayError):
        decode_admin_token(token, "secret-b")


@pytest.mark.anyio
async def test_tampered_token_rejected() -> None:
    token = encode_admin_token("secret-key")
    parts = token.split(".")
    parts[1] = "AAAA"
    bad_token = ".".join(parts)
    with pytest.raises(GatewayError):
        decode_admin_token(bad_token, "secret-key")


@pytest.mark.anyio
async def test_empty_token_rejected() -> None:
    with pytest.raises(GatewayError):
        decode_admin_token("", "secret-key")
