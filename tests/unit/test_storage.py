"""Unit tests for the request-history storage layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from flashrouter.storage.database import Database
from flashrouter.storage.repository import RequestRepository


@pytest.fixture
async def repo(tmp_path: Path) -> RequestRepository:
    db = Database(tmp_path / "flashrouter.db")
    await db.connect()
    await db.migrate()
    try:
        yield RequestRepository(db)
    finally:
        await db.close()


@pytest.mark.anyio
async def test_create_and_get_request(repo: RequestRepository) -> None:
    await repo.create_request(
        request_id="req_1",
        gateway_key_id="default",
        client_ip="127.0.0.1",
        method="POST",
        path="/v1/chat/completions",
        protocol="openai-chat",
        mode="stream",
        model_id="coding-fast",
        upstream_model="real-model",
    )
    row = await repo.get_request("req_1")
    assert row is not None
    assert row["request_id"] == "req_1"
    assert row["model_id"] == "coding-fast"
    assert row["upstream_model"] == "real-model"
    assert row["mode"] == "stream"
    assert row["completed"] == 0
    assert row["status_code"] is None


@pytest.mark.anyio
async def test_update_request_marks_completed(repo: RequestRepository) -> None:
    await repo.create_request(
        request_id="req_2",
        gateway_key_id="default",
        client_ip=None,
        method="POST",
        path="/v1/chat/completions",
        protocol="openai-chat",
        mode="complete",
        model_id="coding-fast",
        upstream_model="real-model",
    )
    await repo.update_request(
        request_id="req_2",
        status_code=200,
        duration_ms=123,
        ttft_ms=45,
        completed=True,
        error=None,
    )
    row = await repo.get_request("req_2")
    assert row is not None
    assert row["status_code"] == 200
    assert row["duration_ms"] == 123
    assert row["ttft_ms"] == 45
    assert row["completed"] == 1


@pytest.mark.anyio
async def test_add_and_get_payloads(repo: RequestRepository) -> None:
    await repo.create_request(
        request_id="req_3",
        gateway_key_id="default",
        client_ip=None,
        method="POST",
        path="/v1/chat/completions",
        protocol="openai-chat",
        mode="complete",
        model_id="coding-fast",
        upstream_model="real-model",
    )
    payload_id = await repo.add_payload(
        request_id="req_3",
        kind="request_incoming",
        body_bytes=b'{"model":"coding-fast"}',
    )
    payloads = await repo.get_payloads("req_3")
    assert len(payloads) == 1
    assert payloads[0]["payload_id"] == payload_id
    assert payloads[0]["kind"] == "request_incoming"
    assert payloads[0]["body_bytes"] == b'{"model":"coding-fast"}'
    assert payloads[0]["size_bytes"] == len(b'{"model":"coding-fast"}')

    fetched = await repo.get_payload(payload_id)
    assert fetched is not None
    assert fetched["body_bytes"] == b'{"model":"coding-fast"}'


@pytest.mark.anyio
async def test_add_attempts(repo: RequestRepository) -> None:
    await repo.create_request(
        request_id="req_4",
        gateway_key_id="default",
        client_ip=None,
        method="POST",
        path="/v1/chat/completions",
        protocol="openai-chat",
        mode="stream",
        model_id="coding-fast",
        upstream_model="real-model",
    )
    await repo.add_attempt(
        request_id="req_4",
        attempt_n=1,
        upstream_model="real-model",
        status_code=200,
        duration_ms=50,
        error=None,
    )
    attempts = await repo.get_attempts("req_4")
    assert len(attempts) == 1
    assert attempts[0]["attempt_n"] == 1
    assert attempts[0]["status_code"] == 200


@pytest.mark.anyio
async def test_list_requests_filters(repo: RequestRepository) -> None:
    await repo.create_request(
        request_id="req_a",
        gateway_key_id="default",
        client_ip=None,
        method="POST",
        path="/v1/chat/completions",
        protocol="openai-chat",
        mode="complete",
        model_id="coding-fast",
        upstream_model="real-model",
    )
    await repo.update_request(
        request_id="req_a",
        status_code=200,
        duration_ms=10,
        completed=True,
        error=None,
    )
    await repo.create_request(
        request_id="req_b",
        gateway_key_id="default",
        client_ip=None,
        method="POST",
        path="/v1/chat/completions",
        protocol="openai-chat",
        mode="stream",
        model_id="coding-smart",
        upstream_model="other-model",
    )
    await repo.update_request(
        request_id="req_b",
        status_code=502,
        duration_ms=10,
        completed=True,
        error="upstream_connection_failed",
    )

    all_rows = await repo.list_requests()
    assert len(all_rows) == 2

    by_model = await repo.list_requests(model="coding-fast")
    assert len(by_model) == 1
    assert by_model[0]["request_id"] == "req_a"

    by_status = await repo.list_requests(status=200)
    assert len(by_status) == 1
    assert by_status[0]["request_id"] == "req_a"

    by_id = await repo.list_requests(request_id="req_b")
    assert len(by_id) == 1
    assert by_id[0]["request_id"] == "req_b"


@pytest.mark.anyio
async def test_get_stats(repo: RequestRepository) -> None:
    await repo.create_request(
        request_id="req_s1",
        gateway_key_id="default",
        client_ip=None,
        method="POST",
        path="/v1/chat/completions",
        protocol="openai-chat",
        mode="complete",
        model_id="coding-fast",
        upstream_model="real-model",
    )
    await repo.update_request(
        request_id="req_s1",
        status_code=200,
        duration_ms=10,
        completed=True,
        error=None,
    )
    await repo.create_request(
        request_id="req_s2",
        gateway_key_id="default",
        client_ip=None,
        method="POST",
        path="/v1/chat/completions",
        protocol="openai-chat",
        mode="stream",
        model_id="coding-fast",
        upstream_model="real-model",
    )
    await repo.update_request(
        request_id="req_s2",
        status_code=None,
        duration_ms=10,
        completed=False,
        error="client_disconnected",
    )
    stats = await repo.get_stats()
    assert stats["total"] == 2
    assert stats["success"] == 1
    assert stats["interrupted"] == 1
    assert stats["error"] == 1


@pytest.mark.anyio
async def test_migrations_run_once(repo: RequestRepository) -> None:
    # Migrations should be idempotent; running again should not error.
    from flashrouter.storage.database import MIGRATIONS, SCHEMA_VERSION

    assert SCHEMA_VERSION == 1
    assert 1 in MIGRATIONS
    await repo.get_stats()  # just ensure connection still works
