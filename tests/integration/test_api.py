from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.conftest import StaticStream, auth_headers, gateway_client, make_settings


@pytest.mark.anyio
async def test_no_auth_required_for_inference(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
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
    async with gateway_client(settings, handler) as (client, _):
        # No auth headers needed
        chat = await client.post(
            "/v1/chat/completions",
            json={"model": "coding-fast", "messages": [{"role": "user", "content": "ping"}]},
        )

    assert chat.status_code == 200
    assert chat.json()["choices"][0]["message"]["content"] == "pong"
    assert len(calls) == 1


@pytest.mark.anyio
async def test_models_endpoint_lists_configured_aliases(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("models endpoint must not contact upstream")

    settings = make_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, app):
        repo = app.state.request_repository
        assert repo is not None
        # Seed an alias matching settings.models
        await repo.create_provider(
            provider_id="prov_1",
            name="mock-upstream",
            base_url="https://upstream.test/v1",
            protocol="openai-chat",
            enabled=True,
        )
        await repo.create_provider_credential(
            credential_id="cred_1",
            provider_id="prov_1",
            name="primary",
            secret="sk-test",
            enabled=True,
        )
        await repo.create_db_model(
            model_id="model_1",
            provider_id="prov_1",
            credential_id="cred_1",
            upstream_model="real-model",
            enabled=True,
        )
        await repo.create_model_alias(
            alias_id="alias_1",
            alias="coding-fast",
            db_model_id="model_1",
            enabled=True,
        )

        response = await client.get("/v1/models", headers=auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    ids = [m["id"] for m in data["data"]]
    assert "coding-fast" in ids


@pytest.mark.anyio
async def test_non_streaming_proxy_maps_model_and_filters_headers(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
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
            headers={"X-Request-ID": "upstream-request-id"},
        )

    settings = make_settings(tmp_path, headers={"X-Configured": "yes"})
    request_body = {
        "model": "coding-fast",
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": 0.2,
        "tools": [{"type": "function", "function": {"name": "test"}}],
    }

    async with gateway_client(settings, handler) as (client, _):
        response = await client.post(
            "/v1/chat/completions",
            headers={
                **auth_headers(),
                "Cookie": "client-session=secret",
                "X-Forwarded-For": "203.0.113.10",
                "CF-Connecting-IP": "203.0.113.10",
                "User-Agent": "client-sdk",
            },
            json=request_body,
        )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "pong"
    assert response.headers["x-request-id"] == "upstream-request-id"
    assert response.headers["x-flashrouter-request-id"]

    assert len(captured) == 1
    upstream_request = captured[0]
    assert upstream_request.headers["authorization"] == "Bearer sk-upstream-test"
    assert upstream_request.headers["x-configured"] == "yes"
    assert upstream_request.headers["user-agent"] == "FlashRouter/0.1.0"
    assert "cookie" not in upstream_request.headers
    assert "x-forwarded-for" not in upstream_request.headers
    assert "cf-connecting-ip" not in upstream_request.headers

    sent_body = json.loads(upstream_request.content)
    assert sent_body["model"] == "real-model"
    assert sent_body["temperature"] == 0.2
    assert sent_body["tools"] == request_body["tools"]


@pytest.mark.anyio
async def test_unknown_model_is_rejected_before_dispatch(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    async with gateway_client(make_settings(tmp_path), handler) as (client, _):
        response = await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "not-configured", "messages": []},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_not_found"
    assert calls == []


@pytest.mark.anyio
async def test_malformed_and_invalid_requests(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid requests must not reach upstream")

    async with gateway_client(make_settings(tmp_path), handler) as (client, _):
        malformed = await client.post(
            "/v1/chat/completions",
            headers={**auth_headers(), "Content-Type": "application/json"},
            content=b"{not-json",
        )
        missing_model = await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"messages": []},
        )
        missing_messages = await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "coding-fast"},
        )

    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "invalid_request"
    assert missing_model.status_code == 400
    assert missing_model.json()["error"]["param"] == "model"
    assert missing_messages.status_code == 400
    assert missing_messages.json()["error"]["param"] == "messages"


@pytest.mark.anyio
async def test_upstream_error_status_and_body_are_preserved(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"message": "blocked by policy", "type": "policy_error"}},
            headers={"X-Request-ID": "provider-request-id"},
        )

    async with gateway_client(make_settings(tmp_path), handler) as (client, _):
        response = await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "coding-fast", "messages": []},
        )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "blocked by policy"
    assert response.headers["x-request-id"] == "provider-request-id"


@pytest.mark.anyio
async def test_upstream_connection_error_is_502(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with gateway_client(make_settings(tmp_path), handler) as (client, _):
        response = await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "coding-fast", "messages": []},
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_connection_failed"


@pytest.mark.anyio
async def test_upstream_timeout_is_504(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async with gateway_client(make_settings(tmp_path), handler) as (client, _):
        response = await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "coding-fast", "messages": []},
        )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"


@pytest.mark.anyio
async def test_streaming_response_is_forwarded(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream", "X-Request-ID": "stream-id"},
            stream=StaticStream(
                [b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n']
            ),
        )

    async with gateway_client(make_settings(tmp_path), handler) as (client, _):
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "coding-fast", "messages": [], "stream": True},
        ) as response:
            body = b"".join([chunk async for chunk in response.aiter_bytes()])

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream"
    assert response.headers["x-request-id"] == "stream-id"
    assert body == (
        b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'
    )


@pytest.mark.anyio
async def test_streaming_upstream_error_is_not_a_stream(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    async with gateway_client(make_settings(tmp_path), handler) as (client, _):
        response = await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "coding-fast", "messages": [], "stream": True},
        )

    assert response.status_code == 429
    assert response.json()["error"]["message"] == "slow down"


@pytest.mark.anyio
async def test_healthz_is_unauthenticated(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("health check must not contact upstream")

    async with gateway_client(make_settings(tmp_path), handler) as (client, _):
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
