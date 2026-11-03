from __future__ import annotations

import sqlite3
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


def _send(client, key: dict) -> str:
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key['token']}"},
        json={"model": "flash", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200, response.text
    return response.headers["X-FlashRouter-Request-ID"]


def _backdate(path: Path, request_ids: list[str]) -> None:
    with sqlite3.connect(path) as conn:
        for request_id in request_ids:
            conn.execute(
                "UPDATE requests SET created_at='2025-01-01 00:00:00.000000' "
                "WHERE request_id=?",
                (request_id,),
            )
        conn.commit()


def test_export_endpoint_writes_a_file(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        _send(client, ctx["key"])

        response = client.get("/admin/api/requests/export", params={"format": "jsonl"})
        assert response.status_code == 200, response.text
        assert "application/x-ndjson" in response.headers["content-type"]
        lines = response.text.splitlines()
        assert len(lines) == 1
        assert '"request"' in lines[0]
        assert '"attempts"' in lines[0]
        assert list((settings.exports_dir).glob("*.jsonl"))


def test_purge_preview_export_and_delete(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        request_ids = [_send(client, ctx["key"]) for _ in range(3)]
        items = client.get("/admin/api/requests").json()["items"]
        newest = items[0]["request_id"]
        old_ids = [request_id for request_id in request_ids if request_id != newest]
        _backdate(settings.database_path, old_ids)

        preview = client.post(
            "/admin/api/requests/purge",
            json={"before": "2026-01-01", "dry_run": True},
        ).json()
        assert preview["matched"] == 2
        assert client.get("/admin/api/requests").json()["total"] == 3

        export = client.get(
            "/admin/api/requests/export", params={"format": "jsonl"}
        )
        assert export.status_code == 200, export.text
        for request_id in old_ids:
            assert request_id in export.text

        result = client.post(
            "/admin/api/requests/purge",
            json={
                "before": "2026-01-01",
                "format": "both",
                "include_payloads": True,
                "dry_run": False,
            },
        ).json()
        assert result["matched"] == 2
        assert result["exported"] == 2
        assert result["deleted"] == 2
        assert result["vacuumed"] is False
        assert [item["format"] for item in result["files"]] == ["jsonl", "csv"]

        remaining = client.get("/admin/api/requests").json()
        assert remaining["total"] == 1
        assert remaining["items"][0]["request_id"] == newest

        stats = client.get("/admin/api/stats").json()
        assert stats["totals"]["requests"] == 1

        for archive in result["files"]:
            download = client.get(f"/admin/api/requests/exports/{archive['file']}")
            assert download.status_code == 200, download.text
            for request_id in old_ids:
                assert request_id in download.text
            assert newest not in download.text


def test_purge_rejects_missing_or_future_cutoff(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        _send(client, ctx["key"])

        missing = client.post("/admin/api/requests/purge", json={})
        assert missing.status_code == 422

        future = client.post(
            "/admin/api/requests/purge", json={"before": "2999-01-01"}
        )
        assert future.status_code == 400
        assert client.get("/admin/api/requests").json()["total"] == 1


def test_purge_defaults_to_dry_run(settings: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion())

    client, _ = build_client(settings, handler)
    with client:
        ctx = _setup(client)
        request_id = _send(client, ctx["key"])
        _backdate(settings.database_path, [request_id])

        response = client.post(
            "/admin/api/requests/purge", json={"before": "2026-01-01"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["dry_run"] is True
        assert client.get("/admin/api/requests").json()["total"] == 1
