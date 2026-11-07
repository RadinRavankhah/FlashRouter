from __future__ import annotations

import json
from pathlib import Path

import httpx

from tests.conftest import anthropic_message, build_client, chat_completion

CC = {"type": "ephemeral"}


def _provider(client, *, name: str, base_url: str, protocol: str, **extra) -> dict:
    return client.post(
        "/admin/api/providers",
        json={
            "name": name,
            "base_url": base_url,
            "preset": "custom",
            "protocol": protocol,
            **extra,
        },
    ).json()


def _account(client, provider: dict) -> None:
    client.post(
        f"/admin/api/providers/{provider['id']}/accounts",
        json={"name": "acct", "secret": "sk-test"},
    )


def _combo(client, provider: dict, *, model: str, name: str) -> None:
    client.post(
        "/admin/api/combos",
        json={
            "name": name,
            "targets": [{"provider_id": provider["id"], "model": model}],
        },
    )


def _key(client, **extra) -> dict:
    return client.post("/admin/api/keys", json={"name": "k", **extra}).json()


def _model(client, provider: dict, *, model: str, **extra) -> dict:
    return client.post(
        "/admin/api/models",
        json={"provider_id": provider["id"], "model": model, **extra},
    ).json()


def _markers(body: dict) -> list[dict]:
    found: list[dict] = []
    for message in body.get("messages") or []:
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("cache_control"):
                    found.append(block["cache_control"])
    for block in body.get("system") or []:
        if isinstance(block, dict) and block.get("cache_control"):
            found.append(block["cache_control"])
    for tool in body.get("tools") or []:
        if isinstance(tool, dict) and tool.get("cache_control"):
            found.append(tool["cache_control"])
    return found


def test_anthropic_messages_get_cache_breakpoints(settings: Path):
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=anthropic_message())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="claude",
            base_url="https://claude.test/v1",
            protocol="anthropic-messages",
        )
        _account(client, provider)
        _combo(client, provider, model="claude-haiku", name="coding")
        key = _key(client)

        response = client.post(
            "/v1/messages",
            headers={"x-api-key": key["token"]},
            json={
                "model": "coding",
                "max_tokens": 64,
                "system": "You are an agent.",
                "tools": [{"name": "read", "input_schema": {"type": "object"}}],
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "hello"}],
                    },
                    {"role": "user", "content": [{"type": "text", "text": "next"}]},
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = captured["body"]
        assert body["system"][0]["cache_control"] == CC
        assert body["tools"][-1]["cache_control"] == CC
        assert body["messages"][1]["content"][-1]["cache_control"] == CC
        assert len(_markers(body)) == 3


def test_key_policy_off_strips_client_markers(settings: Path):
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=anthropic_message())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="claude",
            base_url="https://claude.test/v1",
            protocol="anthropic-messages",
        )
        _account(client, provider)
        _combo(client, provider, model="claude-haiku", name="coding")
        key = _key(client, cache_policy="off")

        response = client.post(
            "/v1/messages",
            headers={"x-api-key": key["token"]},
            json={
                "model": "coding",
                "max_tokens": 64,
                "system": [{"type": "text", "text": "sys", "cache_control": CC}],
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        assert _markers(captured["body"]) == []


def test_key_policy_force_injects_for_openai_provider(settings: Path):
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="chat",
            base_url="https://chat.test/v1",
            protocol="openai-chat",
        )
        _account(client, provider)
        _combo(client, provider, model="claude-haiku", name="coding")
        key = _key(client, cache_policy="force")

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key['token']}"},
            json={
                "model": "coding",
                "messages": [
                    {"role": "system", "content": "You are an agent."},
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                    {"role": "user", "content": "next"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = captured["body"]
        assert body["messages"][0]["content"][0]["cache_control"] == CC
        assert body["messages"][2]["content"][0]["cache_control"] == CC


def test_openai_provider_uses_automatic_caching_by_default(settings: Path):
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="chat",
            base_url="https://chat.test/v1",
            protocol="openai-chat",
        )
        _account(client, provider)
        _combo(client, provider, model="gpt", name="coding")
        key = _key(client)

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key['token']}"},
            json={
                "model": "coding",
                "messages": [
                    {"role": "system", "content": "You are an agent."},
                    {"role": "user", "content": "hi"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = captured["body"]
        assert _markers(body) == []
        assert body["prompt_cache_key"].startswith("fr_")


def test_openai_cache_can_be_disabled_per_key(settings: Path):
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="chat",
            base_url="https://chat.test/v1",
            protocol="openai-chat",
        )
        _account(client, provider)
        _combo(client, provider, model="gpt", name="coding")
        key = _key(client, cache_policy="off")

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key['token']}"},
            json={
                "model": "coding",
                "messages": [
                    {"role": "system", "content": "You are an agent."},
                    {"role": "user", "content": "hi"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        assert _markers(captured["body"]) == []


def test_model_policy_off_scrubs_body_and_headers(settings: Path):
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["headers"] = {
            name.lower(): value for name, value in request.headers.items()
        }
        return httpx.Response(200, json=anthropic_message())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="claude",
            base_url="https://claude.test/v1",
            protocol="anthropic-messages",
            headers={
                "Cache-Control": "max-age=60",
                "Pragma": "no-cache",
                "x-flashrouter-cache": "force",
            },
        )
        _account(client, provider)
        _model(client, provider, model="claude-haiku", cache_policy="off")
        _combo(client, provider, model="claude-haiku", name="coding")
        key = _key(client, cache_policy="force")

        response = client.post(
            "/v1/messages",
            headers={
                "x-api-key": key["token"],
                "anthropic-beta": "prompt-caching-2024-07-31, tools-2024-04-04",
            },
            json={
                "model": "coding",
                "max_tokens": 64,
                "prompt_cache_key": "client-key",
                "cache_control": CC,
                "system": [{"type": "text", "text": "sys", "cache_control": CC}],
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        body = captured["body"]
        headers = captured["headers"]
        assert isinstance(body, dict)
        assert isinstance(headers, dict)
        assert _markers(body) == []
        assert "cache_control" not in body
        assert "prompt_cache_key" not in body
        assert "cache-control" not in headers
        assert "pragma" not in headers
        assert "x-flashrouter-cache" not in headers
        assert headers["anthropic-beta"] == "tools-2024-04-04"


def test_model_policy_off_applies_to_catalog_route(settings: Path):
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="chat",
            base_url="https://chat.test/v1",
            protocol="openai-chat",
        )
        _account(client, provider)
        _model(client, provider, model="gpt", cache_policy="off")
        key = _key(client)

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key['token']}"},
            json={
                "model": "gpt",
                "prompt_cache_key": "client-key",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        assert "prompt_cache_key" not in captured["body"]
        assert _markers(captured["body"]) == []


def test_model_policy_off_applies_to_provider_prefix_route(settings: Path):
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="chat",
            base_url="https://chat.test/v1",
            protocol="openai-chat",
        )
        _account(client, provider)
        _model(client, provider, model="gpt", cache_policy="off")
        key = _key(client)

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key['token']}"},
            json={
                "model": "chat/gpt",
                "prompt_cache_key": "client-key",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        assert "prompt_cache_key" not in captured["body"]
        assert _markers(captured["body"]) == []


def test_model_cache_settings_are_exposed_and_updated(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="chat",
            base_url="https://chat.test/v1",
            protocol="openai-chat",
        )
        created = _model(
            client,
            provider,
            model="gpt",
            cache_policy="off",
            cache_ttl="1h",
        )
        listed = client.get("/admin/api/models").json()
        entry = next(model for model in listed if model["id"] == created["id"])
        assert entry["cache_policy"] == "off"
        assert entry["cache_ttl"] == "1h"

        response = client.put(
            f"/admin/api/models/{created['id']}",
            json={
                "price_in": 1,
                "price_out": 2,
                "cache_policy": "force",
                "cache_ttl": "5m",
            },
        )
        assert response.status_code == 200, response.text
        updated = next(
            model
            for model in client.get("/admin/api/models").json()
            if model["id"] == created["id"]
        )
        assert updated["cache_policy"] == "force"
        assert updated["cache_ttl"] == "5m"



def test_prompt_cache_key_is_retried_without_on_upstream_400(settings: Path):
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "prompt_cache_key" in body:
            return httpx.Response(
                400,
                json={"error": {"message": "Unknown parameter: prompt_cache_key"}},
            )
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="chat",
            base_url="https://chat.test/v1",
            protocol="openai-chat",
        )
        _account(client, provider)
        _combo(client, provider, model="gpt", name="coding")
        key = _key(client)

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key['token']}"},
            json={
                "model": "coding",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        assert "prompt_cache_key" in bodies[0]
        assert "prompt_cache_key" not in bodies[1]

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key['token']}"},
            json={
                "model": "coding",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        assert "prompt_cache_key" not in bodies[2]


def test_openai_provider_can_opt_into_anthropic_markers(settings: Path):
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="claude-proxy",
            base_url="https://proxy.test/v1",
            protocol="openai-chat",
            cache_markers="anthropic",
        )
        _account(client, provider)
        _combo(client, provider, model="claude-haiku", name="coding")
        key = _key(client)

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key['token']}"},
            json={
                "model": "coding",
                "messages": [
                    {"role": "system", "content": "You are an agent."},
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                    {"role": "user", "content": "next"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = captured["body"]
        assert body["messages"][0]["content"][0]["cache_control"] == CC
        assert body["messages"][2]["content"][0]["cache_control"] == CC


def test_request_header_can_disable_injection(settings: Path):
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=anthropic_message())

    client, _ = build_client(settings, handler)
    with client:
        provider = _provider(
            client,
            name="claude",
            base_url="https://claude.test/v1",
            protocol="anthropic-messages",
        )
        _account(client, provider)
        _combo(client, provider, model="claude-haiku", name="coding")
        key = _key(client)

        response = client.post(
            "/v1/messages",
            headers={
                "x-api-key": key["token"],
                "x-flashrouter-cache": "off",
            },
            json={
                "model": "coding",
                "max_tokens": 64,
                "system": "You are an agent.",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        assert _markers(captured["body"]) == []
