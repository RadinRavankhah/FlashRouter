from __future__ import annotations

import json
from pathlib import Path

import httpx

from tests.conftest import build_client, chat_completion


def _setup(
    client,
    *,
    name: str = "mock",
    base_url: str = "https://mock.test/v1",
    model: str = "mock-model",
    combo: str = "flash",
) -> dict:
    provider = client.post(
        "/admin/api/providers",
        json={"name": name, "base_url": base_url, "preset": "custom"},
    ).json()
    client.post(
        f"/admin/api/providers/{provider['id']}/accounts",
        json={"name": "acct", "secret": "sk-test"},
    )
    client.post(
        "/admin/api/models",
        json={
            "provider_id": provider["id"],
            "model": model,
            "price_in": 1.0,
            "price_out": 2.0,
        },
    )
    client.post(
        "/admin/api/combos",
        json={
            "name": combo,
            "targets": [{"provider_id": provider["id"], "model": model}],
        },
    )
    key = client.post("/admin/api/keys", json={"name": "test"}).json()
    return {"provider": provider, "key": key}


def _auth(key: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {key['token']}"}


def test_chat_completion_end_to_end(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer sk-test"
        return httpx.Response(200, json=chat_completion())

    client, upstream = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        response = client.post(
            "/v1/chat/completions",
            headers=_auth(ctx["key"]),
            json={"model": "flash", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["choices"][0]["message"]["content"] == "hello"

        requests = client.get("/admin/api/requests").json()
        assert requests["total"] == 1
        item = requests["items"][0]
        assert item["status"] == "success"
        assert item["input_tokens"] == 10
        assert item["output_tokens"] == 5
        assert item["cost"] > 0

        models = client.get("/v1/models", headers=_auth(ctx["key"])).json()
        ids = {m["id"] for m in models["data"]}
        assert "flash" in ids
        assert "mock/mock-model" in ids


def test_fallback_on_rate_limit(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.test":
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=chat_completion(content="second"))

    client, upstream = build_client(settings, handler)
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
        key = client.post("/admin/api/keys", json={"name": "k"}).json()

        response = client.post(
            "/v1/chat/completions",
            headers=_auth(key),
            json={"model": "failover", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["choices"][0]["message"]["content"] == "second"

        detail = client.get(
            f"/admin/api/requests/{response.headers['X-FlashRouter-Request-ID']}"
        ).json()
        assert detail["status"] == "success"
        assert len(detail["attempts"]) == 2
        assert detail["attempts"][0]["http_status"] == 429
        assert detail["attempts"][1]["status"] == "success"


def test_streaming_forwards_and_records_usage(settings: Path):
    async def stream_body():
        for chunk in [
            b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}\n\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2}}\n\n',
            b"data: [DONE]\n\n",
        ]:
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=stream_body()
        )

    client, upstream = build_client(settings, handler)
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
        assert "Hel" in response.text
        assert "[DONE]" in response.text

        item = client.get("/admin/api/requests").json()["items"][0]
        assert item["status"] == "success"
        assert item["stream"] == 1
        assert item["input_tokens"] == 4
        assert item["output_tokens"] == 2


def test_auth_is_enforced_once_keys_exist(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion())

    client, upstream = build_client(settings, handler)
    with client:
        _setup(client)
        missing = client.post(
            "/v1/chat/completions",
            json={"model": "flash", "messages": []},
        )
        assert missing.status_code == 401
        wrong = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer nope"},
            json={"model": "flash", "messages": []},
        )
        assert wrong.status_code == 401


def test_unknown_model_returns_404(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json=chat_completion())

    client, upstream = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        response = client.post(
            "/v1/chat/completions",
            headers=_auth(ctx["key"]),
            json={"model": "does-not-exist", "messages": []},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "model_not_found"


def test_token_saver_bypass_header(settings: Path):
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=chat_completion())

    client, upstream = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        big = "\n".join(["duplicate line"] * 400)
        payload = {"model": "flash", "messages": [{"role": "tool", "content": big}]}

        client.post("/v1/chat/completions", headers=_auth(ctx["key"]), json=payload)
        client.post(
            "/v1/chat/completions",
            headers={**_auth(ctx["key"]), "X-FlashRouter-Token-Saver": "off"},
            json=payload,
        )

        assert len(captured[0]["messages"][0]["content"]) < len(big)
        assert captured[1]["messages"][0]["content"] == big


def test_provider_model_direct_routing(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion())

    client, upstream = build_client(settings, handler)
    with client:
        ctx = _setup(client, name="mock")
        response = client.post(
            "/v1/chat/completions",
            headers=_auth(ctx["key"]),
            json={"model": "mock/mock-model", "messages": [{"role": "user", "content": "x"}]},
        )
        assert response.status_code == 200, response.text
