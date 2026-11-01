from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from flashrouter.app import create_app
from tests.conftest import build_client, chat_completion


async def _disconnect_mid_stream(settings) -> dict:
    async def stream_body():
        for _ in range(50):
            yield b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'
            await asyncio.sleep(0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=stream_body()
        )

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(settings, http_client=upstream)
    async with app.router.lifespan_context(app):
        repo = app.state.repository
        provider_id = await repo.create_provider(
            name="mock", base_url="https://mock.test/v1"
        )
        await repo.create_account(provider_id=provider_id, name="acct", secret="sk")
        await repo.upsert_model(provider_id=provider_id, model="m")
        await repo.create_combo(
            name="flash", targets=[{"provider_id": provider_id, "model": "m"}]
        )

        payload = json.dumps(
            {
                "model": "flash",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            }
        ).encode()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/chat/completions",
            "raw_path": b"/v1/chat/completions",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
        }
        request_sent = False
        disconnected = asyncio.Event()
        chunks = 0

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": payload, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal chunks
            if message["type"] == "http.response.body" and message.get("more_body"):
                chunks += 1
                if chunks == 2:
                    disconnected.set()

        await app(scope, receive, send)

        item = (await repo.list_requests())["items"][0]
        detail = await repo.get_request(item["request_id"])
        result = {
            "status": item["status"],
            "finished_at": item["finished_at"],
            "attempt_status": detail["attempts"][0]["status"],
            "attempt_finished_at": detail["attempts"][0]["finished_at"],
        }
    await upstream.aclose()
    return result


def test_client_disconnect_mid_stream_finalizes_request(settings: Path):
    result = asyncio.run(_disconnect_mid_stream(settings))
    assert result["status"] == "interrupted"
    assert result["finished_at"] is not None
    assert result["attempt_status"] == "interrupted"
    assert result["attempt_finished_at"] is not None


def test_upstream_transport_error_falls_back_to_next_target(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.test":
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json=chat_completion(content="second"))

    client, _ = build_client(settings, handler)
    with client:
        first = client.post(
            "/admin/api/providers",
            json={"name": "first", "base_url": "https://first.test/v1"},
        ).json()
        second = client.post(
            "/admin/api/providers",
            json={"name": "second", "base_url": "https://second.test/v1"},
        ).json()
        for provider in (first, second):
            client.post(
                f"/admin/api/providers/{provider['id']}/accounts",
                json={"name": "acct", "secret": "sk"},
            )
        client.post(
            "/admin/api/combos",
            json={
                "name": "failover",
                "targets": [
                    {"provider_id": first["id"], "model": "m1"},
                    {"provider_id": second["id"], "model": "m2"},
                ],
            },
        )

        response = client.post(
            "/v1/chat/completions",
            json={"model": "failover", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["choices"][0]["message"]["content"] == "second"

        detail = client.get(
            f"/admin/api/requests/{response.headers['X-FlashRouter-Request-ID']}"
        ).json()
        assert detail["status"] == "success"
        assert detail["attempts"][0]["status"] == "error"
        assert detail["attempts"][0]["error_type"] == "connection_error"
        assert detail["attempts"][1]["status"] == "success"


def test_upstream_transport_error_without_fallback_is_recorded(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client, _ = build_client(settings, handler)
    with client:
        provider = client.post(
            "/admin/api/providers",
            json={"name": "mock", "base_url": "https://mock.test/v1"},
        ).json()
        client.post(
            f"/admin/api/providers/{provider['id']}/accounts",
            json={"name": "acct", "secret": "sk"},
        )
        client.post(
            "/admin/api/models",
            json={"provider_id": provider["id"], "model": "mock-model"},
        )

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock/mock-model",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 502, response.text

        item = client.get("/admin/api/requests").json()["items"][0]
        assert item["status"] == "error"
        assert item["error_type"] == "upstream_error"
        assert item["attempts"] == 1
        assert item["finished_at"] is not None
