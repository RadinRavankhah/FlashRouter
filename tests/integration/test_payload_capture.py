from __future__ import annotations

import json
from pathlib import Path

import httpx

from tests.conftest import build_client, chat_completion


def _setup(client) -> dict:
    provider = client.post(
        "/admin/api/providers",
        json={"name": "mock", "base_url": "https://mock.test/v1", "preset": "custom"},
    ).json()
    client.post(
        f"/admin/api/providers/{provider['id']}/accounts",
        json={"name": "acct", "secret": "sk-test"},
    )
    client.post(
        "/admin/api/models",
        json={"provider_id": provider["id"], "model": "mock-model"},
    )
    client.post(
        "/admin/api/combos",
        json={
            "name": "flash",
            "targets": [{"provider_id": provider["id"], "model": "mock-model"}],
        },
    )
    key = client.post("/admin/api/keys", json={"name": "test"}).json()
    return {"provider": provider, "key": key}


def _auth(key: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {key['token']}"}


def _payload_map(client, request_id: str) -> dict[str, str]:
    detail = client.get(f"/admin/api/requests/{request_id}").json()
    return {payload["kind"]: payload["body"] for payload in detail["payloads"]}


def test_large_prompt_and_response_are_not_truncated(settings: Path):
    response_content = "R" * 250_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion(content=response_content))

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        prompt = "P" * 300_000
        response = client.post(
            "/v1/chat/completions",
            headers=_auth(ctx["key"]),
            json={"model": "flash", "messages": [{"role": "user", "content": prompt}]},
        )
        assert response.status_code == 200, response.text

        payloads = _payload_map(
            client, response.headers["X-FlashRouter-Request-ID"]
        )
        assert prompt in payloads["incoming"]
        assert "(truncated)" not in payloads["incoming"]
        assert response_content in payloads["response"]
        assert "(truncated)" not in payloads["response"]


def test_streaming_keeps_full_text_and_raw_sse(settings: Path):
    chunk_text = "x" * 1000

    async def stream_body():
        for _ in range(100):
            payload = {"choices": [{"delta": {"content": chunk_text}}]}
            yield f"data: {json.dumps(payload)}\n\n".encode()
        yield b"data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=stream_body(),
        )

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        response = client.post(
            "/v1/chat/completions",
            headers=_auth(ctx["key"]),
            json={
                "model": "flash",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text

        payloads = _payload_map(
            client, response.headers["X-FlashRouter-Request-ID"]
        )
        raw = payloads["response_raw"]
        assert raw.count("data:") == 101
        assert "(truncated)" not in raw
        summary = json.loads(payloads["response"])
        assert len(summary["text"]) == 100_000


def test_upstream_error_body_is_stored(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "bad things happened", "type": "invalid_request"}},
        )

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        response = client.post(
            "/v1/chat/completions",
            headers=_auth(ctx["key"]),
            json={"model": "flash", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 400, response.text

        payloads = _payload_map(
            client, response.headers["X-FlashRouter-Request-ID"]
        )
        assert "bad things happened" in payloads["response"]
        assert "(truncated)" not in payloads["response"]


def test_payload_max_chars_caps_when_configured(settings: Path):
    settings.payload_max_chars = 1000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        response = client.post(
            "/v1/chat/completions",
            headers=_auth(ctx["key"]),
            json={
                "model": "flash",
                "messages": [{"role": "user", "content": "P" * 5000}],
            },
        )
        assert response.status_code == 200, response.text

        payloads = _payload_map(
            client, response.headers["X-FlashRouter-Request-ID"]
        )
        incoming = payloads["incoming"]
        assert incoming.endswith("...(truncated)")
        assert len(incoming) == 1000 + len("...(truncated)")
