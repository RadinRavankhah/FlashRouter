from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from flashrouter.storage.database import Database
from flashrouter.storage.repository import Repository


@asynccontextmanager
async def _repo(tmp_path: Path):
    database = Database(tmp_path / "flashrouter.db")
    await database.connect()
    await database.migrate()
    try:
        yield database, Repository(database)
    finally:
        await database.close()


async def _seed(repo: Repository, database: Database) -> None:
    rows = [
        {
            "request_id": "req-1",
            "requested_model": "gpt-4o",
            "provider": "OpenAI",
            "model": "gpt-4o-2024",
            "key_id": 1,
            "key_name": "Claude Code",
            "endpoint": "chat/completions",
            "status": "success",
            "cost": 0.5,
            "duration_ms": 500,
            "account_id": 1,
            "account_name": "acct-fast",
            "error_type": None,
            "error_message": None,
            "created_at": "2026-01-01 10:00:00.000000",
        },
        {
            "request_id": "req-2",
            "requested_model": "gpt-4o-mini",
            "provider": "DeepSeek",
            "model": "deepseek-chat",
            "key_id": 2,
            "key_name": "Cursor",
            "endpoint": "messages",
            "status": "error",
            "cost": 0.1,
            "duration_ms": 2000,
            "account_id": 2,
            "account_name": "acct-slow",
            "error_type": "rate_limit_error",
            "error_message": "Too many requests",
            "created_at": "2026-01-02 10:00:00.000000",
        },
        {
            "request_id": "req-3",
            "requested_model": "claude-3-5-sonnet",
            "provider": "Anthropic",
            "model": "claude-3-5-sonnet-latest",
            "key_id": 1,
            "key_name": "Claude Code",
            "endpoint": "messages",
            "status": "success",
            "cost": 1.5,
            "duration_ms": 800,
            "account_id": 1,
            "account_name": "acct-fast",
            "error_type": None,
            "error_message": None,
            "created_at": "2026-01-03 10:00:00.000000",
        },
    ]
    for row in rows:
        await repo.create_request(
            request_id=row["request_id"],
            requested_model=row["requested_model"],
            key_id=row["key_id"],
            key_name=row["key_name"],
            stream=False,
            endpoint=row["endpoint"],
        )
        await repo.add_attempt(
            request_id=row["request_id"],
            attempt_n=1,
            provider_id=1,
            provider_name=row["provider"],
            account_id=row["account_id"],
            account_name=row["account_name"],
            model=row["model"],
        )
        await repo.finish_request(
            row["request_id"],
            {
                "resolved_provider": row["provider"],
                "resolved_model": row["model"],
                "status": row["status"],
                "cost": row["cost"],
                "duration_ms": row["duration_ms"],
                "error_type": row["error_type"],
                "error_message": row["error_message"],
                "attempts": 1,
            },
        )
        await database.conn.execute(
            "UPDATE requests SET created_at=? WHERE request_id=?",
            (row["created_at"], row["request_id"]),
        )
    await database.conn.commit()


def _ids(result: dict) -> list[str]:
    return [item["request_id"] for item in result["items"]]


def test_model_filter_is_a_substring_match(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            result = await repo.list_requests(model="4o")
            assert _ids(result) == ["req-2", "req-1"]
            assert result["total"] == 2

    asyncio.run(run())


def test_exact_filters(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            assert _ids(await repo.list_requests(provider="OpenAI")) == ["req-1"]
            assert _ids(await repo.list_requests(endpoint="messages")) == ["req-3", "req-2"]
            assert _ids(await repo.list_requests(status="error")) == ["req-2"]
            assert _ids(await repo.list_requests(error_type="rate_limit_error")) == ["req-2"]
            assert _ids(await repo.list_requests(key_id=1)) == ["req-3", "req-1"]
            assert _ids(await repo.list_requests(account_id=2)) == ["req-2"]

    asyncio.run(run())


def test_free_text_search_covers_metadata_and_attempts(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            assert _ids(await repo.list_requests(q="Claude")) == ["req-3", "req-1"]
            assert _ids(await repo.list_requests(q="too many")) == ["req-2"]
            assert _ids(await repo.list_requests(q="acct-fast")) == ["req-3", "req-1"]
            assert _ids(await repo.list_requests(q="DeepSeek")) == ["req-2"]
            assert _ids(await repo.list_requests(q="req-2")) == ["req-2"]

    asyncio.run(run())


def test_date_window_is_applied(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            from_ts = "2026-01-02 00:00:00.000000"
            to_ts = "2026-01-03 00:00:00.000000"
            assert _ids(await repo.list_requests(from_ts=from_ts)) == ["req-3", "req-2"]
            assert _ids(await repo.list_requests(to_ts=to_ts)) == ["req-2", "req-1"]
            assert _ids(
                await repo.list_requests(from_ts=from_ts, to_ts=to_ts)
            ) == ["req-2"]

    asyncio.run(run())


def test_sorting(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            assert _ids(await repo.list_requests(sort="newest")) == ["req-3", "req-2", "req-1"]
            assert _ids(await repo.list_requests(sort="oldest")) == ["req-1", "req-2", "req-3"]
            assert _ids(await repo.list_requests(sort="slowest")) == ["req-2", "req-3", "req-1"]
            assert _ids(await repo.list_requests(sort="cost")) == ["req-3", "req-1", "req-2"]
            assert _ids(await repo.list_requests(sort="unknown")) == ["req-3", "req-2", "req-1"]

    asyncio.run(run())


def test_like_wildcards_are_escaped(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await repo.create_request(
                request_id="literal",
                requested_model="model-100%_x",
                key_id=None,
                key_name=None,
                stream=False,
            )
            assert _ids(await repo.list_requests(q="100%")) == ["literal"]
            assert _ids(await repo.list_requests(q="%")) == ["literal"]
            assert _ids(await repo.list_requests(q="_")) == ["literal"]
            assert _ids(await repo.list_requests(q="does_not_exist")) == []

    asyncio.run(run())


def test_pagination_reports_filtered_total(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            first = await repo.list_requests(limit=2, offset=0)
            assert first["total"] == 3
            assert len(first["items"]) == 2
            second = await repo.list_requests(limit=2, offset=2)
            assert second["total"] == 3
            assert _ids(second) == ["req-1"]
            filtered = await repo.list_requests(status="success", limit=1)
            assert filtered["total"] == 2
            assert _ids(filtered) == ["req-3"]

    asyncio.run(run())


def test_filter_options(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            options = await repo.list_request_filter_options()
            assert options["providers"] == ["Anthropic", "DeepSeek", "OpenAI"]
            assert options["endpoints"] == ["chat/completions", "messages"]
            assert options["error_types"] == ["rate_limit_error"]
            assert options["keys"] == [
                {"key_id": 1, "key_name": "Claude Code"},
                {"key_id": 2, "key_name": "Cursor"},
            ]
            assert options["accounts"] == [
                {"account_id": 1, "account_name": "acct-fast"},
                {"account_id": 2, "account_name": "acct-slow"},
            ]

    asyncio.run(run())


def test_indexes_created_by_migration(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, _repo_obj):
            async with database.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ) as cursor:
                names = {row["name"] for row in await cursor.fetchall()}
            assert {
                "idx_requests_endpoint",
                "idx_requests_key",
                "idx_requests_provider",
                "idx_requests_error_type",
                "idx_attempts_account",
            } <= names

    asyncio.run(run())


def test_v5_database_gets_filter_indexes(tmp_path: Path):
    path = tmp_path / "flashrouter.db"

    async def migrate() -> None:
        database = Database(path)
        await database.connect()
        await database.migrate()
        await database.close()

    asyncio.run(migrate())

    connection = sqlite3.connect(path)
    for name in (
        "idx_requests_endpoint",
        "idx_requests_key",
        "idx_requests_provider",
        "idx_requests_error_type",
        "idx_attempts_account",
    ):
        connection.execute(f"DROP INDEX IF EXISTS {name}")
    connection.execute("DELETE FROM schema_migrations WHERE version=6")
    connection.commit()
    connection.close()

    async def indexes() -> set[str]:
        database = Database(path)
        await database.connect()
        await database.migrate()
        try:
            async with database.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ) as cursor:
                return {row["name"] for row in await cursor.fetchall()}
        finally:
            await database.close()

    names = asyncio.run(indexes())
    assert {
        "idx_requests_endpoint",
        "idx_requests_key",
        "idx_requests_provider",
        "idx_requests_error_type",
        "idx_attempts_account",
    } <= names
