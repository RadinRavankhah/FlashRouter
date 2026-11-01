from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from flashrouter.storage.database import Database
from flashrouter.storage.migrations import MIGRATIONS


def _make_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT);
        INSERT INTO schema_migrations(version, applied_at) VALUES (1, '2020-01-01');
        CREATE TABLE providers (id INTEGER PRIMARY KEY, name TEXT);
        """
    )
    connection.commit()
    connection.close()


def _table_names(path: Path) -> set[str]:
    async def run() -> set[str]:
        database = Database(path)
        await database.connect()
        await database.migrate()
        async with database.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            names = {row["name"] for row in await cursor.fetchall()}
        await database.close()
        return names

    return asyncio.run(run())


def test_legacy_database_is_archived_and_recreated(tmp_path: Path):
    path = tmp_path / "flashrouter.db"
    _make_legacy_database(path)

    names = _table_names(path)

    assert "combo_targets" in names
    assert "flashrouter_meta" in names
    archived = list(tmp_path.glob("flashrouter.legacy-*.db"))
    assert archived, "legacy database should be archived"


def test_fresh_database_migrates_without_archive(tmp_path: Path):
    path = tmp_path / "flashrouter.db"

    names = _table_names(path)

    assert "combo_targets" in names
    assert not list(tmp_path.glob("flashrouter.legacy-*.db"))


def test_cache_columns_and_pricing_are_added(tmp_path: Path):
    path = tmp_path / "flashrouter.db"
    _table_names(path)

    connection = sqlite3.connect(path)
    try:
        request_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(requests)")
        }
        attempt_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(request_attempts)")
        }
        usage_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(usage_records)")
        }
        account_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(accounts)")
        }
        model_columns = {row[1] for row in connection.execute("PRAGMA table_info(models)")}
        provider_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(providers)")
        }
        key_columns = {row[1] for row in connection.execute("PRAGMA table_info(keys)")}
    finally:
        connection.close()

    assert {"cache_read_tokens", "cache_write_tokens"} <= request_columns
    assert {"cache_read_tokens", "cache_write_tokens"} <= attempt_columns
    assert {"cache_read_tokens", "cache_write_tokens"} <= usage_columns
    assert "cache_read_tokens" in account_columns
    assert "price_cache_in" in model_columns
    assert "price_cache_write" in model_columns
    assert {"cache_markers", "cache_ttl"} <= provider_columns
    assert {"cache_policy", "cache_ttl"} <= key_columns


def test_v4_database_upgrades_with_cache_policy_defaults(tmp_path: Path):
    path = tmp_path / "flashrouter.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)"
    )
    connection.execute(
        "CREATE TABLE flashrouter_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO flashrouter_meta(key, value) VALUES ('schema', 'flashrouter')"
    )
    for version in range(1, 5):
        connection.executescript(MIGRATIONS[version])
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, '2020-01-01')",
            (version,),
        )
    connection.execute(
        "INSERT INTO providers(name, base_url, created_at, updated_at) "
        "VALUES ('p', 'https://p.test/v1', 'x', 'x')"
    )
    connection.execute(
        "INSERT INTO keys(name, token, created_at) VALUES ('k', 'fr-test', 'x')"
    )
    connection.commit()
    connection.close()

    _table_names(path)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        provider = dict(connection.execute("SELECT * FROM providers").fetchone())
        key = dict(connection.execute("SELECT * FROM keys").fetchone())
    finally:
        connection.close()

    assert provider["cache_markers"] == "auto"
    assert provider["cache_ttl"] == ""
    assert key["cache_policy"] == "auto"
    assert key["cache_ttl"] == ""


def test_v2_database_upgrades_to_v3(tmp_path: Path):
    path = tmp_path / "flashrouter.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)"
    )
    connection.execute(
        "CREATE TABLE flashrouter_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO flashrouter_meta(key, value) VALUES ('schema', 'flashrouter')"
    )
    connection.executescript(MIGRATIONS[1])
    connection.executescript(MIGRATIONS[2])
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (1, '2020-01-01')"
    )
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (2, '2020-01-01')"
    )
    connection.commit()
    connection.close()

    _table_names(path)

    connection = sqlite3.connect(path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(requests)")}
        versions = {
            row[0] for row in connection.execute("SELECT version FROM schema_migrations")
        }
    finally:
        connection.close()

    assert "cache_read_tokens" in columns
    assert 3 in versions


def test_pending_requests_are_recovered_from_attempts(tmp_path: Path):
    path = tmp_path / "flashrouter.db"
    _table_names(path)

    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO requests(request_id, created_at, requested_model, status) "
            "VALUES ('fr_1', '2026-01-01 00:00:00.000000', 'mock', 'pending')"
        )
        connection.execute(
            "INSERT INTO request_attempts(request_id, attempt_n, provider_name, model, "
            "started_at, finished_at, status, input_tokens, output_tokens, cost) "
            "VALUES ('fr_1', 1, 'mock', 'mock-model', '2026-01-01 00:00:00.000000', "
            "'2026-01-01 00:00:01.000000', 'success', 10, 5, 0.25)"
        )
        connection.commit()
    finally:
        connection.close()

    _table_names(path)  # reopen and migrate/recover

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        request = dict(
            connection.execute(
                "SELECT * FROM requests WHERE request_id='fr_1'"
            ).fetchone()
        )
    finally:
        connection.close()

    assert request["status"] == "interrupted"
    assert request["finished_at"] is not None
    assert request["resolved_provider"] == "mock"
    assert request["resolved_model"] == "mock-model"
    assert request["input_tokens"] == 10
    assert request["output_tokens"] == 5
    assert request["cost"] == 0.25
    assert request["attempts"] == 1


def test_existing_schema_is_not_archived(tmp_path: Path):
    path = tmp_path / "flashrouter.db"
    _table_names(path)  # create schema

    names = _table_names(path)  # run again

    assert "combo_targets" in names
    assert not list(tmp_path.glob("flashrouter.legacy-*.db"))
