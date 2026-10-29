"""v0.3 backend tests: gateway-key auth, multi-upstream resolution, test endpoint,
attribution filters, and CSRF protection."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import httpx
import pytest

from tests.conftest import (
    auth_headers,
    gateway_client,
    make_settings,
)


def _configured_settings(tmp_path: Path):
    """Return settings with a config file on disk so auth is enforced."""
    (tmp_path / "config.toml").write_text("# configured for auth tests\n", encoding="utf-8")
    return make_settings(tmp_path)


class _MockClientFactory:
    """Wrap httpx.AsyncClient so every outbound call hits a MockTransport handler."""

    _original = httpx.AsyncClient

    def __init__(self, handler) -> None:
        self.handler = handler

    def __call__(self, *args, **kwargs) -> httpx.AsyncClient:
        return self._original(transport=httpx.MockTransport(self.handler))


@pytest.mark.anyio
async def test_chat_completions_requires_gateway_key(tmp_path: Path) -> None:
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

    settings = _configured_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, _):
        missing = await client.post(
            "/v1/chat/completions",
            json={"model": "coding-fast", "messages": [{"role": "user", "content": "ping"}]},
        )
        invalid = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer wrong-key"},
            json={"model": "coding-fast", "messages": [{"role": "user", "content": "ping"}]},
        )
        valid = await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "coding-fast", "messages": [{"role": "user", "content": "ping"}]},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200


@pytest.mark.anyio
async def test_disabled_gateway_key_is_rejected(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("disabled key must not reach upstream")

    settings = _configured_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, app):
        repo = app.state.request_repository
        assert repo is not None
        await repo.create_gateway_key(
            key_id="disabled_key",
            name="Disabled",
            secret="sk-disabled",
            enabled=False,
        )

        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-disabled"},
            json={"model": "coding-fast", "messages": []},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "key_disabled"


@pytest.mark.anyio
async def test_multi_upstream_uses_provider_credential(tmp_path: Path) -> None:
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
        )

    settings = _configured_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, app):
        repo = app.state.request_repository
        assert repo is not None
        await repo.create_provider(
            provider_id="prov_second",
            name="Second",
            base_url="https://second-upstream.test/v1",
            protocol="openai-chat",
            enabled=True,
        )
        await repo.create_provider_credential(
            credential_id="cred_second",
            provider_id="prov_second",
            name="second-cred",
            secret="sk-second-secret",
            enabled=True,
        )
        await repo.create_db_model(
            model_id="model_second",
            provider_id="prov_second",
            credential_id="cred_second",
            upstream_model="second-model",
            enabled=True,
        )
        await repo.create_model_alias(
            alias_id="alias_second",
            alias="second-model",
            db_model_id="model_second",
            enabled=True,
        )
        await repo.create_gateway_key(
            key_id="key_1",
            name="Key One",
            secret=settings.gateway_api_key(),
            enabled=True,
        )

        with mock.patch.object(
            httpx, "AsyncClient", _MockClientFactory(handler)
        ):
            response = await client.post(
                "/v1/chat/completions",
                headers=auth_headers(),
                json={"model": "second-model", "messages": [{"role": "user", "content": "hi"}]},
            )

    assert response.status_code == 200
    assert len(captured) == 1
    upstream_request = captured[0]
    # Request must be routed to the provider's base URL, not settings.upstream.
    assert str(upstream_request.url).startswith("https://second-upstream.test/v1")
    # Authorization must use the DB-stored credential secret.
    assert upstream_request.headers["authorization"] == "Bearer sk-second-secret"


@pytest.mark.anyio
async def test_models_endpoint_requires_auth(tmp_path: Path) -> None:
    settings = _configured_settings(tmp_path)
    async with gateway_client(settings, lambda req: httpx.Response(200, json={})) as (
        client,
        _,
    ):
        missing = await client.get("/v1/models")
        invalid = await client.get(
            "/v1/models", headers={"Authorization": "Bearer wrong-key"}
        )
        valid = await client.get("/v1/models", headers=auth_headers())

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200


@pytest.mark.anyio
async def test_test_provider_endpoint(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"object": "list", "data": []})

    settings = _configured_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, app):
        repo = app.state.request_repository
        assert repo is not None
        await repo.create_provider(
            provider_id="prov_test",
            name="Test Provider",
            base_url="https://test-upstream.test/v1",
            protocol="openai-chat",
            enabled=True,
        )
        await repo.create_provider_credential(
            credential_id="cred_test",
            provider_id="prov_test",
            name="test-cred",
            secret="sk-test-cred",
            enabled=True,
        )

        with mock.patch.object(
            httpx, "AsyncClient", _MockClientFactory(handler)
        ):
            response = await client.post(
                "/admin/v1/providers/prov_test/test",
                headers={**auth_headers(), "Origin": "http://gateway.test"},
                json={"model": "test-model", "max_tokens": 1},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["status"] == 200
    assert data["credential_id"] == "cred_test"
    assert data["credential_name"] == "test-cred"
    assert len(captured) == 1
    assert captured[0].headers["authorization"] == "Bearer sk-test-cred"


@pytest.mark.anyio
async def test_request_filters_by_gateway_key_and_credential(tmp_path: Path) -> None:
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

    settings = _configured_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, app):
        repo = app.state.request_repository
        assert repo is not None
        await repo.create_provider(
            provider_id="prov_f",
            name="First",
            base_url="https://first.test/v1",
            protocol="openai-chat",
            enabled=True,
        )
        await repo.create_provider_credential(
            credential_id="cred_f",
            provider_id="prov_f",
            name="first",
            secret="sk-first",
            enabled=True,
        )
        await repo.create_db_model(
            model_id="model_f",
            provider_id="prov_f",
            credential_id="cred_f",
            upstream_model="first-model",
            enabled=True,
        )
        await repo.create_model_alias(
            alias_id="alias_f",
            alias="first-model",
            db_model_id="model_f",
            enabled=True,
        )
        await repo.create_gateway_key(
            key_id="key_a", name="Key A", secret="sk-key-a", enabled=True
        )
        await repo.create_gateway_key(
            key_id="key_b", name="Key B", secret="sk-key-b", enabled=True
        )

        async def post(secret: str) -> httpx.Response:
            return await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {secret}"},
                json={"model": "first-model", "messages": [{"role": "user", "content": "hi"}]},
            )

        await post("sk-key-a")
        await post("sk-key-b")

        by_a = await client.get(
            "/admin/v1/requests?gateway_key=key_a",
            headers={**auth_headers(), "Origin": "http://gateway.test"},
        )
        by_b = await client.get(
            "/admin/v1/requests?gateway_key=key_b",
            headers={**auth_headers(), "Origin": "http://gateway.test"},
        )
        by_cred = await client.get(
            "/admin/v1/requests?credential=cred_f",
            headers={**auth_headers(), "Origin": "http://gateway.test"},
        )

    assert by_a.status_code == 200
    assert by_b.status_code == 200
    assert by_cred.status_code == 200
    assert len(by_a.json()["requests"]) == 1
    assert len(by_b.json()["requests"]) == 1
    assert len(by_cred.json()["requests"]) == 2
    assert by_a.json()["requests"][0]["gateway_key_id"] == "key_a"
    assert by_b.json()["requests"][0]["gateway_key_id"] == "key_b"


@pytest.mark.anyio
async def test_csrf_origin_required_for_admin_mutations(tmp_path: Path) -> None:
    settings = _configured_settings(tmp_path)
    async with gateway_client(settings, lambda req: httpx.Response(200, json={})) as (
        client,
        _,
    ):
        body = {
            "name": "CSRF Provider",
            "base_url": "https://csrf.test/v1",
            "protocol": "openai-chat",
            "enabled": True,
        }
        no_origin = await client.post(
            "/admin/v1/providers",
            headers=auth_headers(),
            json=body,
        )
        matching_origin = await client.post(
            "/admin/v1/providers",
            headers={**auth_headers(), "Origin": "http://gateway.test"},
            json=body,
        )
        referer_origin = await client.post(
            "/admin/v1/providers",
            headers={
                **auth_headers(),
                "Referer": "http://gateway.test/settings",
            },
            json={**body, "name": "CSRF Provider 2"},
        )

    assert no_origin.status_code == 403
    assert matching_origin.status_code == 200
    assert referer_origin.status_code == 200


@pytest.mark.anyio
async def test_delete_credential_preserves_history(tmp_path: Path) -> None:
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

    settings = _configured_settings(tmp_path)
    async with gateway_client(settings, handler) as (client, app):
        repo = app.state.request_repository
        assert repo is not None
        await repo.create_provider(
            provider_id="prov_hist",
            name="Hist",
            base_url="https://hist.test/v1",
            protocol="openai-chat",
            enabled=True,
        )
        await repo.create_provider_credential(
            credential_id="cred_hist",
            provider_id="prov_hist",
            name="hist",
            secret="sk-hist",
            enabled=True,
        )
        await repo.create_gateway_key(
            key_id="key_hist", name="Hist Key", secret=settings.gateway_api_key(), enabled=True
        )

        await client.post(
            "/v1/chat/completions",
            headers=auth_headers(),
            json={"model": "coding-fast", "messages": [{"role": "user", "content": "hi"}]},
        )

        before = await repo.list_requests()
        assert len(before) >= 1

        # Deleting the credential must not cascade-delete requests/attempts.
        await repo.delete_provider_credential("cred_hist")

        after = await repo.list_requests()
        assert len(after) == len(before)
        assert after[0]["request_id"] == before[0]["request_id"]
