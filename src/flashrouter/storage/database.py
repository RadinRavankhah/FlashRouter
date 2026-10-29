"""SQLite storage backend with WAL mode and versioned migrations."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

SCHEMA_VERSION = 5

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
    2: """
    CREATE TABLE IF NOT EXISTS providers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        base_url TEXT NOT NULL,
        protocol TEXT NOT NULL DEFAULT 'openai-chat',
        headers TEXT DEFAULT '{}',
        connect_timeout_seconds REAL DEFAULT 10.0,
        read_timeout_seconds REAL DEFAULT 180.0,
        verify_tls INTEGER DEFAULT 1,
        trust_env INTEGER DEFAULT 0,
        follow_redirects INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS provider_credentials (
        id TEXT PRIMARY KEY,
        provider_id TEXT NOT NULL REFERENCES providers(id),
        name TEXT NOT NULL,
        secret TEXT NOT NULL,
        enabled INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS gateway_keys (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        secret TEXT NOT NULL,
        enabled INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS db_models (
        id TEXT PRIMARY KEY,
        provider_id TEXT NOT NULL REFERENCES providers(id),
        credential_id TEXT REFERENCES provider_credentials(id),
        upstream_model TEXT NOT NULL,
        enabled INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS model_aliases (
        id TEXT PRIMARY KEY,
        alias TEXT NOT NULL UNIQUE,
        db_model_id TEXT NOT NULL REFERENCES db_models(id),
        enabled INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_model_aliases_alias ON model_aliases(alias);
    CREATE INDEX IF NOT EXISTS idx_db_models_provider_id ON db_models(provider_id);
    CREATE INDEX IF NOT EXISTS idx_provider_credentials_provider_id
    ON provider_credentials(provider_id);
    ALTER TABLE attempts ADD COLUMN credential_id TEXT;
    INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '2');
    """,
    3: """
    ALTER TABLE gateway_keys ADD COLUMN last_used TEXT;
    INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '3');
    """,
    4: """
    -- v0.4 analytics: usage, pricing, cost reconciliation
    CREATE TABLE IF NOT EXISTS usage_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL REFERENCES requests(request_id),
        attempt_id TEXT REFERENCES attempts(attempt_id),
        input_tokens INTEGER,
        output_tokens INTEGER,
        cache_read_tokens INTEGER,
        cache_write_tokens INTEGER,
        reasoning_tokens INTEGER,
        raw_usage TEXT,
        usage_source TEXT,
        completeness TEXT DEFAULT 'unknown',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_usage_request_id ON usage_records(request_id);
    CREATE TABLE IF NOT EXISTS price_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_id TEXT NOT NULL,
        input_price_per_1m REAL,
        output_price_per_1m REAL,
        cache_read_price_per_1m REAL,
        currency TEXT DEFAULT 'USD',
        version_tag TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_price_model_version ON price_versions(model_id, version_tag);
    CREATE TABLE IF NOT EXISTS cost_reconciliation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL REFERENCES requests(request_id),
        effort_cost REAL,
        billed_cost REAL,
        estimated_cost REAL,
        status TEXT DEFAULT 'pending',
        adjustment_reason TEXT,
        created_at TEXT NOT NULL
    );
    INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '4');
    """,
    5: """
    -- v0.5 budgets/restrictions
    ALTER TABLE gateway_keys ADD COLUMN daily_budget REAL DEFAULT 0;
    ALTER TABLE gateway_keys ADD COLUMN monthly_budget REAL DEFAULT 0;
    ALTER TABLE gateway_keys ADD COLUMN lifetime_budget REAL DEFAULT 0;
    ALTER TABLE gateway_keys ADD COLUMN budget_reset_hour INTEGER DEFAULT 0;
    ALTER TABLE gateway_keys ADD COLUMN allowed_models TEXT DEFAULT '[]';
    ALTER TABLE provider_credentials ADD COLUMN daily_budget REAL DEFAULT 0;
    ALTER TABLE provider_credentials ADD COLUMN allowed_models TEXT DEFAULT '[]';
    CREATE TABLE IF NOT EXISTS budget_reservations (
        reservation_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL REFERENCES requests(request_id),
        gateway_key_id TEXT,
        credential_id TEXT,
        reserved_cost REAL NOT NULL DEFAULT 0,
        settled_cost REAL,
        status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_budget_req ON budget_reservations(request_id);
    INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '5');
    """,
}


_ALTER_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+(?P<table>\w+)\s+ADD\s+COLUMN\s+(?P<column>\w+)",
    re.IGNORECASE,
)


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

    async def _column_exists(self, table: str, column: str) -> bool:
        async with self.connection.execute(
            f"PRAGMA table_info({table})"
        ) as cursor:
            rows = await cursor.fetchall()
        return any(row[1] == column for row in rows)

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
                script = MIGRATIONS[version]
                # Guard ALTER TABLE ADD COLUMN so migrations stay idempotent
                # when re-run against an already-migrated database.
                for match in _ALTER_ADD_COLUMN.finditer(script):
                    table = match.group("table")
                    column = match.group("column")
                    if await self._column_exists(table, column):
                        script = script.replace(match.group(0), "")
                if script.strip():
                    await conn.executescript(script)
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
