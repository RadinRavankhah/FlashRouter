"""SQLite storage backend with WAL mode and versioned migrations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

SCHEMA_VERSION = 1

MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS requests (
        request_id TEXT PRIMARY KEY,
        gateway_key_id TEXT NOT NULL DEFAULT 'default',
        client_ip TEXT,
        method TEXT NOT NULL,
        path TEXT NOT NULL,
        protocol TEXT NOT NULL DEFAULT 'openai-chat',
        mode TEXT NOT NULL,
        model_id TEXT NOT NULL,
        upstream_model TEXT,
        status_code INTEGER,
        duration_ms INTEGER,
        ttft_ms INTEGER,
        completed INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS attempts (
        attempt_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL REFERENCES requests(request_id),
        attempt_n INTEGER NOT NULL DEFAULT 1,
        upstream_model TEXT,
        status_code INTEGER,
        duration_ms INTEGER,
        error TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payloads (
        payload_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL REFERENCES requests(request_id),
        attempt_id TEXT REFERENCES attempts(attempt_id),
        kind TEXT NOT NULL,
        body_bytes BLOB NOT NULL,
        size_bytes INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_requests_created_at ON requests(created_at);
    CREATE INDEX IF NOT EXISTS idx_requests_model_id ON requests(model_id);
    CREATE INDEX IF NOT EXISTS idx_requests_status_code ON requests(status_code);
    CREATE INDEX IF NOT EXISTS idx_attempts_request_id ON attempts(request_id);
    CREATE INDEX IF NOT EXISTS idx_payloads_request_id ON payloads(request_id);
    INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1');
    """,
}


class Database:
    """Wrapper around aiosqlite with WAL mode and schema migrations."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._connection = await aiosqlite.connect(str(self.db_path))
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA busy_timeout=5000")
        await self._connection.execute("PRAGMA synchronous=NORMAL")

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database not connected")
        return self._connection

    async def migrate(self) -> None:
        conn = self.connection
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        async with conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ) as cursor:
            row = await cursor.fetchone()
        current_version = int(row[0]) if row else 0

        for version in sorted(MIGRATIONS):
            if version > current_version:
                await conn.executescript(MIGRATIONS[version])
                await conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                    (str(version),),
                )
                await conn.commit()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = self.connection
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
