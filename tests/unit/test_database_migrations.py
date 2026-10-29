from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from flashrouter.storage.database import Database


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


def test_existing_schema_is_not_archived(tmp_path: Path):
    path = tmp_path / "flashrouter.db"
    _table_names(path)  # create schema

    names = _table_names(path)  # run again

    assert "combo_targets" in names
    assert not list(tmp_path.glob("flashrouter.legacy-*.db"))
