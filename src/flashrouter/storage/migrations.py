"""Versioned SQLite schema migrations."""

from __future__ import annotations

SCHEMA_VERSION = 3

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS providers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        preset TEXT NOT NULL DEFAULT 'custom',
        base_url TEXT NOT NULL,
        protocol TEXT NOT NULL DEFAULT 'openai-chat',
        headers TEXT NOT NULL DEFAULT '{}',
        enabled INTEGER NOT NULL DEFAULT 1,
        priority INTEGER NOT NULL DEFAULT 100,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        secret TEXT NOT NULL DEFAULT '',
        weight INTEGER NOT NULL DEFAULT 1,
        priority INTEGER NOT NULL DEFAULT 100,
        enabled INTEGER NOT NULL DEFAULT 1,
        cooling_until TEXT,
        last_error TEXT,
        cooldown_seconds INTEGER NOT NULL DEFAULT 60,
        requests INTEGER NOT NULL DEFAULT 0,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS models (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
        model TEXT NOT NULL,
        display_name TEXT,
        price_in REAL NOT NULL DEFAULT 0,
        price_out REAL NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1,
        source TEXT NOT NULL DEFAULT 'manual',
        created_at TEXT NOT NULL,
        UNIQUE(provider_id, model)
    );

    CREATE TABLE IF NOT EXISTS combos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS combo_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        combo_id INTEGER NOT NULL REFERENCES combos(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
        model TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        token TEXT NOT NULL UNIQUE,
        enabled INTEGER NOT NULL DEFAULT 1,
        allowed_combos TEXT NOT NULL DEFAULT '[]',
        last_used_at TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        finished_at TEXT,
        key_id INTEGER,
        key_name TEXT,
        requested_model TEXT NOT NULL,
        resolved_provider TEXT,
        resolved_model TEXT,
        stream INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        http_status INTEGER,
        error_type TEXT,
        error_message TEXT,
        duration_ms INTEGER,
        ttft_ms INTEGER,
        input_tokens INTEGER,
        output_tokens INTEGER,
        cost REAL,
        attempts INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS request_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        attempt_n INTEGER NOT NULL,
        provider_id INTEGER,
        provider_name TEXT,
        account_id INTEGER,
        account_name TEXT,
        model TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        http_status INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',
        error_type TEXT,
        error_message TEXT,
        retry_reason TEXT,
        input_tokens INTEGER,
        output_tokens INTEGER,
        cost REAL
    );

    CREATE TABLE IF NOT EXISTS payloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        attempt_n INTEGER,
        kind TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS usage_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        provider_id INTEGER,
        account_id INTEGER,
        key_id INTEGER,
        model TEXT,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cost REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS operational_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        detail TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_requests_created ON requests(created_at);
    CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
    CREATE INDEX IF NOT EXISTS idx_requests_model ON requests(requested_model);
    CREATE INDEX IF NOT EXISTS idx_attempts_request ON request_attempts(request_id);
    CREATE INDEX IF NOT EXISTS idx_payloads_request ON payloads(request_id);
    CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_records(created_at);
    CREATE INDEX IF NOT EXISTS idx_accounts_provider ON accounts(provider_id);
    CREATE INDEX IF NOT EXISTS idx_targets_combo ON combo_targets(combo_id);
    """,
    2: """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    3: """
    ALTER TABLE requests ADD COLUMN cache_read_tokens INTEGER;
    ALTER TABLE requests ADD COLUMN cache_write_tokens INTEGER;
    ALTER TABLE request_attempts ADD COLUMN cache_read_tokens INTEGER;
    ALTER TABLE request_attempts ADD COLUMN cache_write_tokens INTEGER;
    ALTER TABLE usage_records ADD COLUMN cache_read_tokens INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE usage_records ADD COLUMN cache_write_tokens INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE accounts ADD COLUMN cache_read_tokens INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE models ADD COLUMN price_cache_in REAL;
    """,
}
