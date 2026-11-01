from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.conftest import anthropic_message, build_client


def _setup(
    client,
    *,
    name: str = "mock",
    base_url: str = "https://anthropic.test/v1",
    protocol: str = "anthropic-messages",
    model: str = "claude-test",
    combo: str = "claude",
) -> dict:
    provider = client.post(
        "/admin/api/providers",
        json={
            "name": name,
            "base_url": base_url,
            "preset": "custom",
            "protocol": protocol,
        },
    ).json()
    client.post(
        f"/admin/api/providers/{provider['id']}/accounts",
        json={"name": "acct", "secret": "sk-ant"},
    )
    client.post(
        "/admin/api/models",
        json={
            "provider_id": provider["id"],
            "model": model,
            "price_in": 1.0,
            "price_out": 2.0,
            "price_cache_in": 0.25,
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


def _anth_headers(key: dict, **extra: str) -> dict[str, str]:
    return {"x-api-key": key["token"], **extra}


def test_messages_pass_through_and_records_usage(settings: Path):
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = request.url.query.decode()
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=anthropic_message(
                content="hi there",
                input_tokens=10,
                output_tokens=5,
                cache_read_tokens=4,
                cache_write_tokens=2,
            ),
        )

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        response = client.post(
            "/v1/messages?beta=true",
            headers=_anth_headers(ctx["key"], **{"anthropic-version": "2024-01-01"}),
            json={
                "model": "claude",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["content"][0]["text"] == "hi there"

        headers = captured["headers"]
        assert captured["path"] == "/v1/messages"
        assert captured["query"] == "beta=true"
        assert headers["authorization"] == "Bearer sk-ant"
        assert headers["x-api-key"] == "sk-ant"
        assert headers["anthropic-version"] == "2024-01-01"
        body = captured["body"]
        assert body["model"] == "claude-test"
        assert body["max_tokens"] == 64

        item = client.get("/admin/api/requests").json()["items"][0]
        assert item["endpoint"] == "messages"
        assert item["status"] == "success"
        assert item["input_tokens"] == 16
        assert item["output_tokens"] == 5
        assert item["cache_read_tokens"] == 4
        assert item["cache_write_tokens"] == 2
        assert item["cost"] == pytest.approx(0.000025)


def test_messages_streaming_forwards_and_records_usage(settings: Path):
    async def stream_body():
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-test",
                    "content": [],
                    "stop_reason": None,
                    "usage": {
                        "input_tokens": 8,
                        "output_tokens": 1,
                        "cache_creation_input_tokens": 2,
                        "cache_read_input_tokens": 3,
                    },
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hel"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "lo"},
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 7},
            },
            {"type": "message_stop"},
        ]
        for event in events:
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()

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
            "/v1/messages",
            headers=_anth_headers(ctx["key"]),
            json={
                "model": "claude",
                "max_tokens": 64,
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        assert "Hel" in response.text
        assert "message_stop" in response.text

        item = client.get("/admin/api/requests").json()["items"][0]
        assert item["status"] == "success"
        assert item["stream"] == 1
        assert item["input_tokens"] == 13
        assert item["output_tokens"] == 7
        assert item["cache_read_tokens"] == 3
        assert item["cache_write_tokens"] == 2

        detail = client.get(
            f"/admin/api/requests/{response.headers['X-FlashRouter-Request-ID']}"
        ).json()
        response_payload = json.loads(
            [p for p in detail["payloads"] if p["kind"] == "response"][0]["body"]
        )
        assert response_payload["text"] == "Hello"
        assert response_payload["finish_reason"] == "end_turn"


def test_count_tokens_passes_through_without_usage(settings: Path):
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json={"input_tokens": 42})

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        response = client.post(
            "/v1/messages/count_tokens",
            headers=_anth_headers(ctx["key"]),
            json={"model": "claude", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"input_tokens": 42}
        assert captured["path"] == "/v1/messages/count_tokens"

        item = client.get("/admin/api/requests").json()["items"][0]
        assert item["endpoint"] == "messages/count_tokens"
        assert item["status"] == "success"
        assert item["input_tokens"] == 0

        stats = client.get("/admin/api/stats").json()
        assert stats["totals"]["input_tokens"] == 0
        accounts = client.get(
            f"/admin/api/providers/{ctx['provider']['id']}/accounts"
        ).json()
        assert accounts[0]["input_tokens"] == 0


def test_messages_unknown_model_uses_anthropic_error_envelope(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json=anthropic_message())

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        response = client.post(
            "/v1/messages",
            headers=_anth_headers(ctx["key"]),
            json={"model": "missing", "max_tokens": 8, "messages": []},
        )
        assert response.status_code == 404
        body = response.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "not_found_error"
        assert "missing" in body["error"]["message"]


def test_messages_falls_back_to_next_target(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.test":
            return httpx.Response(
                429,
                json={
                    "type": "error",
                    "error": {"type": "rate_limit_error", "message": "limited"},
                },
            )
        return httpx.Response(200, json=anthropic_message(content="second"))

    client, _ = build_client(settings, handler)
    with client:
        first = client.post(
            "/admin/api/providers",
            json={
                "name": "first",
                "base_url": "https://first.test/v1",
                "protocol": "anthropic-messages",
            },
        ).json()
        second = client.post(
            "/admin/api/providers",
            json={
                "name": "second",
                "base_url": "https://second.test/v1",
                "protocol": "anthropic-messages",
            },
        ).json()
        for provider in (first, second):
            client.post(
                f"/admin/api/providers/{provider['id']}/accounts",
                json={"name": "acct", "secret": "sk-ant"},
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
            "/v1/messages",
            headers=_anth_headers(key),
            json={"model": "failover", "max_tokens": 8, "messages": []},
        )
        assert response.status_code == 200, response.text
        assert response.json()["content"][0]["text"] == "second"

        detail = client.get(
            f"/admin/api/requests/{response.headers['X-FlashRouter-Request-ID']}"
        ).json()
        assert detail["attempts"][0]["http_status"] == 429
        assert detail["attempts"][1]["status"] == "success"


def test_models_listing_supports_both_shapes(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json=anthropic_message())

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        response = client.get("/v1/models", headers=_anth_headers(ctx["key"]))
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "list"
        assert body["has_more"] is False
        assert body["first_id"]
        item = body["data"][0]
        assert item["object"] == "model"
        assert item["type"] == "model"
        assert item["created_at"]


def test_anthropic_preset_sets_protocol_and_base_url(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json=anthropic_message())

    client, _ = build_client(settings, handler)
    with client:
        provider = client.post(
            "/admin/api/providers",
            json={"name": "Anthropic", "preset": "anthropic"},
        ).json()
        assert provider["base_url"] == "https://api.anthropic.com/v1"
        assert provider["protocol"] == "anthropic-messages"

