from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from tests.conftest import build_client, chat_completion


def _setup(client) -> dict:
    provider = client.post(
        "/admin/api/providers",
        json={"name": "mock", "base_url": "https://mock.test/v1", "preset": "custom"},
    ).json()
    account = client.post(
        f"/admin/api/providers/{provider['id']}/accounts",
        json={"name": "acct", "secret": "sk-test"},
    ).json()
    client.post(
        "/admin/api/models",
        json={
            "provider_id": provider["id"],
            "model": "mock-model",
            "price_in": 1.0,
            "price_out": 2.0,
        },
    )
    client.post(
        "/admin/api/combos",
        json={"name": "flash", "targets": [{"provider_id": provider["id"], "model": "mock-model"}]},
    )
    key = client.post("/admin/api/keys", json={"name": "test"}).json()
    return {"provider": provider, "account": account, "key": key}


def test_list_requests_filters(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {ctx['key']['token']}"},
            json={"model": "flash", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200, response.text

        assert client.get("/admin/api/requests", params={"q": "flas"}).json()["total"] == 1
        assert (
            client.get("/admin/api/requests", params={"model": "las"}).json()["total"] == 1
        )
        assert (
            client.get("/admin/api/requests", params={"provider": "mock"}).json()["total"] == 1
        )
        assert (
            client.get("/admin/api/requests", params={"status": "success"}).json()["total"] == 1
        )
        assert (
            client.get(
                "/admin/api/requests",
                params={"endpoint": "chat/completions"},
            ).json()["total"]
            == 1
        )
        assert (
            client.get(
                "/admin/api/requests",
                params={"account_id": ctx["account"]["id"]},
            ).json()["total"]
            == 1
        )
        assert client.get("/admin/api/requests", params={"q": "nope"}).json()["total"] == 0

        today = datetime.now(UTC).date().isoformat()
        tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
        assert (
            client.get("/admin/api/requests", params={"to": today}).json()["total"] == 1
        )
        assert (
            client.get("/admin/api/requests", params={"from": tomorrow}).json()["total"] == 0
        )

        options = client.get("/admin/api/requests/filters").json()
        assert options["providers"] == ["mock"]
        assert options["endpoints"] == ["chat/completions"]
        assert options["keys"] == [{"key_id": ctx["key"]["id"], "key_name": "test"}]
        assert options["accounts"] == [
            {"account_id": ctx["account"]["id"], "account_name": "acct"}
        ]


def test_list_requests_query_validation(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        assert client.get("/admin/api/requests", params={"sort": "nonsense"}).status_code == 200
        response = client.get("/admin/api/requests", params={"from": "not-a-date"})
        assert response.status_code == 400
        assert response.json()["error"]["param"] == "from"
        response = client.get("/admin/api/requests", params={"to": "2026-13-99"})
        assert response.status_code == 400
        assert response.json()["error"]["param"] == "to"
