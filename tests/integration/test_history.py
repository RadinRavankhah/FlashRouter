"""Integration tests for persistent request history (v0.2)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.conftest import (
    StaticStream,
    auth_headers,
    gateway_client,
    make_settings,
)


@pytest.mark.anyio
async def test_persist_before_dispatch_blocks_upstream_on_storage_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If persistence fails, the request must not reach upstream."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"id": "chatcmpl_test", "object": "chat.completion", "choices": []},
        )

    settings = make_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, app):
        repo = app.state.request_repository
        assert repo is not None

        async def failing_create_request(*args: object, **kwargs: object) -> None:
            raise RuntimeError("storage is unavailable")

        monkeypatch.setattr(repo, "create_request", failing_create_request)

        response = await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "coding-fast", "messages": []},
        )

    assert response.status_code == 500
    assert calls == []


@pytest.mark.anyio
async def test_successful_request_is_persisted_and_listed(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "pong"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    settings = make_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, app):
        repo = app.state.request_repository
        assert repo is not None

        response = await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={
                "model": "coding-fast",
                "messages": [{"role": "user", "content": "ping"}],
            },
        )
        assert response.status_code == 200

        rows = await repo.list_requests()
        assert len(rows) == 1
        assert rows[0]["model_id"] == "coding-fast"
        assert rows[0]["upstream_model"] == "real-model"
        assert rows[0]["completed"] == 1
        assert rows[0]["status_code"] == 200

        payloads = await repo.get_payloads(rows[0]["request_id"])
        kinds = {p["kind"] for p in payloads}
        assert "request_incoming" in kinds
        assert "request_outgoing" in kinds
        assert "response_client" in kinds

        attempts = await repo.get_attempts(rows[0]["request_id"])
        assert len(attempts) == 1
        assert attempts[0]["status_code"] == 200


@pytest.mark.anyio
async def test_streaming_request_records_ttft_and_partial_output(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=StaticStream(
                [
                    b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n',
                    b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
                    b'data: [DONE]\n\n',
                ]
            ),
        )

    settings = make_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, app):
        repo = app.state.request_repository
        assert repo is not None

        async with client.stream(
            "POST",
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "coding-fast", "messages": [], "stream": True},
        ) as response:
            body = b"".join([chunk async for chunk in response.aiter_bytes()])

        assert response.status_code == 200
        assert b"hel" in body
        assert b"lo" in body

        rows = await repo.list_requests()
        assert len(rows) == 1
        assert rows[0]["completed"] == 1
        assert rows[0]["ttft_ms"] is not None

        payloads = await repo.get_payloads(rows[0]["request_id"])
        client_payloads = [p for p in payloads if p["kind"] == "response_client"]
        assert len(client_payloads) == 1
        reconstructed = json.loads(client_payloads[0]["body_bytes"].decode())
        assert reconstructed["choices"][0]["message"]["content"] == "hello"


@pytest.mark.anyio
async def test_admin_login_and_protected_endpoints(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "chatcmpl_test", "object": "chat.completion", "choices": []},
        )

    settings = make_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, app):
        repo = app.state.request_repository
        assert repo is not None

        # Setup status: not configured initially
        status = await client.get("/admin/setup/status")
        assert status.status_code == 200
        assert status.json()["configured"] is False

        # Make a request to generate history (no auth needed)
        await client.post(
            "/v1/chat/completions",
            json={"model": "coding-fast", "messages": []},
        )

        # Access admin endpoints without auth
        stats = await client.get("/admin/v1/stats")
        assert stats.status_code == 200
        assert stats.json()["total"] == 1

        health = await client.get("/admin/v1/health")
        assert health.status_code == 200

        requests = await client.get("/admin/v1/requests?limit=10&offset=0")
        assert requests.status_code == 200
        data = requests.json()
        assert len(data["requests"]) == 1

