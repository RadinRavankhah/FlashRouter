"""Data access layer for FlashRouter."""

from __future__ import annotations

import json
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from flashrouter.logging import get_logger
from flashrouter.storage.database import Database

logger = get_logger()

# Timestamps use SQLite-friendly formatting (space separator, UTC).
TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def now_iso() -> str:
    return datetime.now(UTC).strftime(TIME_FORMAT)


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_REQUEST_SORTS = {
    "newest": "r.id DESC",
    "oldest": "r.id ASC",
    "slowest": "r.duration_ms DESC, r.id DESC",
    "cost": "r.cost DESC, r.id DESC",
}


def _decode_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _provider(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["headers"] = _decode_json(data.get("headers"), {})
    data["enabled"] = bool(data.get("enabled"))
    return data


def _account(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["enabled"] = bool(data.get("enabled"))
    return data


def _combo(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["enabled"] = bool(data.get("enabled"))
    return data


def _key(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["enabled"] = bool(data.get("enabled"))
    data["allowed_combos"] = _decode_json(data.get("allowed_combos"), [])
    return data


class Repository:
    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def _conn(self):  # convenience
        return self._db.conn

    # ------------------------------------------------------------------ helpers
    async def _fetchall(self, sql: str, params: tuple = ()) -> list[Any]:
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchall()

    async def _fetchone(self, sql: str, params: tuple = ()) -> Any | None:
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def _write(self, sql: str, params: tuple = ()) -> int:
        cursor = await self._conn.execute(sql, params)
        await self._conn.commit()
        return cursor.lastrowid or 0

    # ---------------------------------------------------------------- providers
    async def list_providers(self) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT p.*, "
            "(SELECT COUNT(*) FROM accounts a WHERE a.provider_id=p.id) AS account_count, "
            "(SELECT COUNT(*) FROM models m WHERE m.provider_id=p.id) AS model_count "
            "FROM providers p ORDER BY p.priority DESC, p.name"
        )
        return [_provider(row) for row in rows]

    async def get_provider(self, provider_id: int) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM providers WHERE id=?", (provider_id,))
        return _provider(row) if row else None

    async def find_provider_by_name(self, name: str) -> dict[str, Any] | None:
        row = await self._fetchone(
            "SELECT * FROM providers WHERE lower(name)=lower(?) LIMIT 1", (name,)
        )
        return _provider(row) if row else None

    async def create_provider(
        self,
        *,
        name: str,
        base_url: str,
        preset: str = "custom",
        protocol: str = "openai-chat",
        headers: dict[str, str] | None = None,
        enabled: bool = True,
        priority: int = 100,
        cache_markers: str = "auto",
        cache_ttl: str = "",
    ) -> int:
        now = now_iso()
        return await self._write(
            "INSERT INTO providers(name, preset, base_url, protocol, headers, enabled, "
            "priority, cache_markers, cache_ttl, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                name,
                preset,
                base_url,
                protocol,
                json.dumps(headers or {}),
                int(enabled),
                priority,
                cache_markers,
                cache_ttl,
                now,
                now,
            ),
        )

    async def update_provider(self, provider_id: int, fields: dict[str, Any]) -> bool:
        allowed = {
            "name",
            "preset",
            "base_url",
            "protocol",
            "headers",
            "enabled",
            "priority",
            "cache_markers",
            "cache_ttl",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "headers" in updates:
            updates["headers"] = json.dumps(updates["headers"] or {})
        if "enabled" in updates:
            updates["enabled"] = int(bool(updates["enabled"]))
        sets = ", ".join(f"{k}=?" for k in updates)
        params = tuple(updates.values()) + (now_iso(), provider_id)
        await self._write(
            f"UPDATE providers SET {sets}, updated_at=? WHERE id=?", params
        )
        return True

    async def delete_provider(self, provider_id: int) -> None:
        await self._write("DELETE FROM providers WHERE id=?", (provider_id,))

    # ----------------------------------------------------------------- accounts
    async def list_accounts(self, provider_id: int | None = None) -> list[dict[str, Any]]:
        if provider_id is None:
            rows = await self._fetchall("SELECT * FROM accounts ORDER BY priority DESC, id")
        else:
            rows = await self._fetchall(
                "SELECT * FROM accounts WHERE provider_id=? ORDER BY priority DESC, id",
                (provider_id,),
            )
        return [_account(row) for row in rows]

    async def get_account(self, account_id: int) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM accounts WHERE id=?", (account_id,))
        return _account(row) if row else None

    async def create_account(
        self,
        *,
        provider_id: int,
        name: str,
        secret: str = "",
        weight: int = 1,
        priority: int = 100,
        enabled: bool = True,
        cooldown_seconds: int = 60,
    ) -> int:
        now = now_iso()
        return await self._write(
            "INSERT INTO accounts(provider_id, name, secret, weight, priority, enabled, "
            "cooldown_seconds, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                provider_id,
                name,
                secret or "",
                max(1, weight),
                priority,
                int(enabled),
                max(1, cooldown_seconds),
                now,
                now,
            ),
        )

    async def update_account(self, account_id: int, fields: dict[str, Any]) -> bool:
        allowed = {
            "name",
            "secret",
            "weight",
            "priority",
            "enabled",
            "cooldown_seconds",
            "cooling_until",
            "last_error",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "enabled" in updates:
            updates["enabled"] = int(bool(updates["enabled"]))
        if "weight" in updates:
            updates["weight"] = max(1, int(updates["weight"]))
        sets = ", ".join(f"{k}=?" for k in updates)
        params = tuple(updates.values()) + (now_iso(), account_id)
        await self._write(f"UPDATE accounts SET {sets}, updated_at=? WHERE id=?", params)
        return True

    async def delete_account(self, account_id: int) -> None:
        await self._write("DELETE FROM accounts WHERE id=?", (account_id,))

    async def eligible_accounts(self, provider_id: int) -> list[dict[str, Any]]:
        now = now_iso()
        rows = await self._fetchall(
            "SELECT * FROM accounts WHERE provider_id=? AND enabled=1 "
            "AND (cooling_until IS NULL OR cooling_until < ?) "
            "ORDER BY priority DESC, id",
            (provider_id, now),
        )
        return [_account(row) for row in rows]

    async def record_account_use(
        self,
        account_id: int,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
    ) -> None:
        await self._write(
            "UPDATE accounts SET requests=requests+1, input_tokens=input_tokens+?, "
            "output_tokens=output_tokens+?, cache_read_tokens=cache_read_tokens+?, "
            "updated_at=? WHERE id=?",
            (input_tokens, output_tokens, cache_read_tokens, now_iso(), account_id),
        )

    async def cooldown_account(self, account_id: int, seconds: int, error: str) -> None:
        from datetime import timedelta

        until = (datetime.now(UTC) + timedelta(seconds=max(1, seconds))).strftime(
            TIME_FORMAT
        )
        await self._write(
            "UPDATE accounts SET cooling_until=?, last_error=?, updated_at=? WHERE id=?",
            (until, error[:500], now_iso(), account_id),
        )

    # ------------------------------------------------------------------- models
    async def list_models(self, provider_id: int | None = None) -> list[dict[str, Any]]:
        base = (
            "SELECT m.*, p.name AS provider_name FROM models m "
            "JOIN providers p ON p.id=m.provider_id"
        )
        if provider_id is None:
            rows = await self._fetchall(base + " ORDER BY p.name, m.model")
        else:
            rows = await self._fetchall(
                base + " WHERE m.provider_id=? ORDER BY m.model", (provider_id,)
            )
        return [dict(row) for row in rows]

    async def upsert_model(
        self,
        *,
        provider_id: int,
        model: str,
        display_name: str | None = None,
        price_in: float = 0,
        price_out: float = 0,
        price_cache_in: float | None = None,
        price_cache_write: float | None = None,
        cache_policy: str = "auto",
        cache_ttl: str = "",
        source: str = "manual",
        enabled: bool = True,
    ) -> int:
        existing = await self._fetchone(
            "SELECT id FROM models WHERE provider_id=? AND model=?", (provider_id, model)
        )
        if existing:
            await self._write(
                "UPDATE models SET display_name=?, price_in=?, price_out=?, "
                "price_cache_in=?, price_cache_write=?, cache_policy=?, cache_ttl=?, "
                "source=?, enabled=? WHERE id=?",
                (
                    display_name,
                    price_in,
                    price_out,
                    price_cache_in,
                    price_cache_write,
                    cache_policy,
                    cache_ttl,
                    source,
                    int(enabled),
                    existing["id"],
                ),
            )
            return int(existing["id"])
        return await self._write(
            "INSERT INTO models(provider_id, model, display_name, price_in, price_out, "
            "price_cache_in, price_cache_write, cache_policy, cache_ttl, source, enabled, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                provider_id,
                model,
                display_name,
                price_in,
                price_out,
                price_cache_in,
                price_cache_write,
                cache_policy,
                cache_ttl,
                source,
                int(enabled),
                now_iso(),
            ),
        )

    async def ensure_model(
        self,
        *,
        provider_id: int,
        model: str,
        source: str = "discover",
        price_in: float | None = None,
        price_out: float | None = None,
        price_cache_in: float | None = None,
        price_cache_write: float | None = None,
    ) -> int:
        """Insert a discovered model and backfill prices only when they are unset."""
        existing = await self._fetchone(
            "SELECT id, price_in, price_out FROM models WHERE provider_id=? AND model=?",
            (provider_id, model),
        )
        if existing:
            if (
                price_in is not None
                and price_out is not None
                and float(existing["price_in"]) == 0
                and float(existing["price_out"]) == 0
            ):
                await self._write(
                    "UPDATE models SET price_in=?, price_out=?, price_cache_in=?, "
                    "price_cache_write=? WHERE id=?",
                    (
                        price_in,
                        price_out,
                        price_cache_in,
                        price_cache_write,
                        existing["id"],
                    ),
                )
            return int(existing["id"])
        return await self._write(
            "INSERT INTO models(provider_id, model, price_in, price_out, price_cache_in, "
            "price_cache_write, source, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                provider_id,
                model,
                price_in or 0,
                price_out or 0,
                price_cache_in,
                price_cache_write,
                source,
                now_iso(),
            ),
        )

    async def update_model(
        self,
        model_id: int,
        *,
        price_in: float,
        price_out: float,
        price_cache_in: float | None,
        price_cache_write: float | None = None,
        cache_policy: str = "auto",
        cache_ttl: str = "",
    ) -> bool:
        changed = await self._write(
            "UPDATE models SET price_in=?, price_out=?, price_cache_in=?, "
            "price_cache_write=?, cache_policy=?, cache_ttl=? WHERE id=?",
            (
                price_in,
                price_out,
                price_cache_in,
                price_cache_write,
                cache_policy,
                cache_ttl,
                model_id,
            ),
        )
        return changed > 0

    async def get_model_cache(
        self, provider_id: int, model: str
    ) -> tuple[str, str]:
        row = await self._fetchone(
            "SELECT cache_policy, cache_ttl FROM models "
            "WHERE provider_id=? AND model=?",
            (provider_id, model),
        )
        if row is None:
            return ("auto", "")
        return (str(row["cache_policy"] or "auto"), str(row["cache_ttl"] or ""))

    async def get_model_price(
        self, provider_id: int, model: str
    ) -> tuple[float, float, float | None, float | None]:
        row = await self._fetchone(
            "SELECT price_in, price_out, price_cache_in, price_cache_write FROM models "
            "WHERE provider_id=? AND model=?",
            (provider_id, model),
        )
        if row is None:
            return (0.0, 0.0, None, None)
        cache_price = row["price_cache_in"]
        write_price = row["price_cache_write"]
        return (
            float(row["price_in"]),
            float(row["price_out"]),
            float(cache_price) if cache_price is not None else None,
            float(write_price) if write_price is not None else None,
        )

    async def models_by_name(self, model: str) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT m.model, p.id AS provider_id, p.name AS provider_name, "
            "p.base_url, p.protocol, p.headers, p.cache_markers, p.cache_ttl, "
            "m.cache_policy AS model_cache_policy, m.cache_ttl AS model_cache_ttl, "
            "p.enabled AS provider_enabled, "
            "p.priority AS provider_priority "
            "FROM models m JOIN providers p ON p.id=m.provider_id "
            "WHERE m.model=? AND m.enabled=1 AND p.enabled=1 "
            "ORDER BY p.priority DESC, p.id",
            (model,),
        )
        return [dict(row) for row in rows]

    async def delete_model(self, model_id: int) -> None:
        await self._write("DELETE FROM models WHERE id=?", (model_id,))

    # -------------------------------------------------------------------- combos
    async def _targets(self, combo_id: int) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT t.id, t.combo_id, t.position, t.provider_id, t.model, t.enabled, "
            "p.name AS provider_name, p.base_url, p.protocol, p.headers, "
            "p.cache_markers, p.cache_ttl, "
            "m.cache_policy AS model_cache_policy, m.cache_ttl AS model_cache_ttl, "
            "p.enabled AS provider_enabled "
            "FROM combo_targets t JOIN providers p ON p.id=t.provider_id "
            "LEFT JOIN models m ON m.provider_id=t.provider_id AND m.model=t.model "
            "WHERE t.combo_id=? ORDER BY t.position",
            (combo_id,),
        )
        result = []
        for row in rows:
            data = dict(row)
            data["enabled"] = bool(data["enabled"])
            data["provider_enabled"] = bool(data["provider_enabled"])
            data["headers"] = _decode_json(data.get("headers"), {})
            result.append(data)
        return result

    async def list_combos(self) -> list[dict[str, Any]]:
        rows = await self._fetchall("SELECT * FROM combos ORDER BY name")
        combos = []
        for row in rows:
            combo = _combo(row)
            combo["targets"] = await self._targets(combo["id"])
            combos.append(combo)
        return combos

    async def get_combo(self, combo_id: int) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM combos WHERE id=?", (combo_id,))
        if row is None:
            return None
        combo = _combo(row)
        combo["targets"] = await self._targets(combo["id"])
        return combo

    async def find_combo(self, name: str) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM combos WHERE name=?", (name,))
        return _combo(row) if row else None

    async def combo_candidates(self, combo_id: int) -> list[dict[str, Any]]:
        targets = await self._targets(combo_id)
        return [
            t
            for t in targets
            if t["enabled"] and t["provider_enabled"]
        ]

    async def create_combo(
        self,
        *,
        name: str,
        description: str = "",
        enabled: bool = True,
        targets: list[dict[str, Any]] | None = None,
    ) -> int:
        now = now_iso()
        combo_id = await self._write(
            "INSERT INTO combos(name, description, enabled, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (name, description, int(enabled), now, now),
        )
        await self._replace_targets(combo_id, targets or [])
        return combo_id

    async def _replace_targets(
        self, combo_id: int, targets: list[dict[str, Any]]
    ) -> None:
        await self._conn.execute("DELETE FROM combo_targets WHERE combo_id=?", (combo_id,))
        for position, target in enumerate(targets):
            await self._conn.execute(
                "INSERT INTO combo_targets(combo_id, position, provider_id, model, enabled) "
                "VALUES (?,?,?,?,?)",
                (
                    combo_id,
                    position,
                    int(target["provider_id"]),
                    str(target["model"]),
                    int(bool(target.get("enabled", True))),
                ),
            )
        await self._conn.commit()

    async def update_combo(
        self,
        combo_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        targets: list[dict[str, Any]] | None = None,
    ) -> bool:
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if description is not None:
            fields["description"] = description
        if enabled is not None:
            fields["enabled"] = int(enabled)
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            await self._write(
                f"UPDATE combos SET {sets}, updated_at=? WHERE id=?",
                tuple(fields.values()) + (now_iso(), combo_id),
            )
        if targets is not None:
            await self._replace_targets(combo_id, targets)
        return True

    async def delete_combo(self, combo_id: int) -> None:
        await self._write("DELETE FROM combos WHERE id=?", (combo_id,))

    # ---------------------------------------------------------------------- keys
    async def list_keys(self) -> list[dict[str, Any]]:
        rows = await self._fetchall("SELECT * FROM keys ORDER BY id")
        return [_key(row) for row in rows]

    async def get_key(self, key_id: int) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM keys WHERE id=?", (key_id,))
        return _key(row) if row else None

    async def get_key_by_token(self, token: str) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM keys WHERE token=?", (token,))
        return _key(row) if row else None

    async def create_key(
        self,
        *,
        name: str,
        token: str | None = None,
        enabled: bool = True,
        allowed_combos: list[str] | None = None,
        cache_policy: str = "auto",
        cache_ttl: str = "",
    ) -> dict[str, Any]:
        token = token or ("fr-" + secrets.token_urlsafe(32))
        key_id = await self._write(
            "INSERT INTO keys(name, token, enabled, allowed_combos, cache_policy, "
            "cache_ttl, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                name,
                token,
                int(enabled),
                json.dumps(allowed_combos or []),
                cache_policy,
                cache_ttl,
                now_iso(),
            ),
        )
        return {"id": key_id, "name": name, "token": token}

    async def update_key(self, key_id: int, fields: dict[str, Any]) -> bool:
        allowed = {
            "name",
            "enabled",
            "allowed_combos",
            "token",
            "cache_policy",
            "cache_ttl",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "enabled" in updates:
            updates["enabled"] = int(bool(updates["enabled"]))
        if "allowed_combos" in updates:
            updates["allowed_combos"] = json.dumps(updates["allowed_combos"] or [])
        sets = ", ".join(f"{k}=?" for k in updates)
        await self._write(
            f"UPDATE keys SET {sets} WHERE id=?", tuple(updates.values()) + (key_id,)
        )
        return True

    async def delete_key(self, key_id: int) -> None:
        await self._write("DELETE FROM keys WHERE id=?", (key_id,))

    async def touch_key(self, key_id: int) -> None:
        await self._write("UPDATE keys SET last_used_at=? WHERE id=?", (now_iso(), key_id))

    async def count_keys(self) -> int:
        row = await self._fetchone("SELECT COUNT(*) AS n FROM keys")
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------ settings
    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = await self._fetchone("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self._write(
            "INSERT INTO settings(key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    # ------------------------------------------------------------------ requests
    async def create_request(
        self,
        *,
        request_id: str,
        requested_model: str,
        key_id: int | None,
        key_name: str | None,
        stream: bool,
        endpoint: str = "chat/completions",
    ) -> None:
        await self._write(
            "INSERT INTO requests(request_id, created_at, key_id, key_name, "
            "requested_model, stream, endpoint) VALUES (?,?,?,?,?,?,?)",
            (
                request_id,
                now_iso(),
                key_id,
                key_name,
                requested_model,
                int(stream),
                endpoint,
            ),
        )

    async def finish_request(self, request_id: str, fields: dict[str, Any]) -> None:
        allowed = {
            "resolved_provider",
            "resolved_model",
            "status",
            "http_status",
            "error_type",
            "error_message",
            "duration_ms",
            "ttft_ms",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "cost",
            "attempts",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        updates["finished_at"] = now_iso()
        sets = ", ".join(f"{k}=?" for k in updates)
        await self._write(
            f"UPDATE requests SET {sets} WHERE request_id=?",
            tuple(updates.values()) + (request_id,),
        )

    async def add_attempt(
        self,
        *,
        request_id: str,
        attempt_n: int,
        provider_id: int | None,
        provider_name: str | None,
        account_id: int | None,
        account_name: str | None,
        model: str | None,
    ) -> int:
        return await self._write(
            "INSERT INTO request_attempts(request_id, attempt_n, provider_id, "
            "provider_name, account_id, account_name, model, started_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                request_id,
                attempt_n,
                provider_id,
                provider_name,
                account_id,
                account_name,
                model,
                now_iso(),
            ),
        )

    async def finish_attempt(self, attempt_id: int, fields: dict[str, Any]) -> None:
        allowed = {
            "http_status",
            "status",
            "error_type",
            "error_message",
            "retry_reason",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "cost",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        updates["finished_at"] = now_iso()
        sets = ", ".join(f"{k}=?" for k in updates)
        await self._write(
            f"UPDATE request_attempts SET {sets} WHERE id=?",
            tuple(updates.values()) + (attempt_id,),
        )

    async def add_payload(
        self, *, request_id: str, kind: str, body: str, attempt_n: int | None = None
    ) -> None:
        try:
            await self._write(
                "INSERT INTO payloads(request_id, attempt_n, kind, body, created_at) "
                "VALUES (?,?,?,?,?)",
                (request_id, attempt_n, kind, body, now_iso()),
            )
        except Exception:
            # Best-effort payload logging must not break a request, but a
            # failure should be visible instead of silently losing data.
            logger.warning(
                "payload_write_failed id=%s kind=%s attempt=%s",
                request_id,
                kind,
                attempt_n,
                exc_info=True,
            )

    async def list_requests(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        model: str | None = None,
        key_id: int | None = None,
        endpoint: str | None = None,
        q: str | None = None,
        provider: str | None = None,
        account_id: int | None = None,
        error_type: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        sort: str = "newest",
    ) -> dict[str, Any]:
        clauses, params = self._request_filter_clause(
            status=status,
            model=model,
            key_id=key_id,
            endpoint=endpoint,
            q=q,
            provider=provider,
            account_id=account_id,
            error_type=error_type,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = _REQUEST_SORTS.get(sort, _REQUEST_SORTS["newest"])
        total_row = await self._fetchone(
            f"SELECT COUNT(*) AS n FROM requests r {where}", tuple(params)
        )
        rows = await self._fetchall(
            f"SELECT * FROM requests r {where} ORDER BY {order} LIMIT ? OFFSET ?",
            tuple(params) + (limit, offset),
        )
        return {
            "total": int(total_row["n"]) if total_row else 0,
            "items": [dict(row) for row in rows],
        }

    def _request_filter_clause(
        self,
        *,
        status: str | None = None,
        model: str | None = None,
        key_id: int | None = None,
        endpoint: str | None = None,
        q: str | None = None,
        provider: str | None = None,
        account_id: int | None = None,
        error_type: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("r.status=?")
            params.append(status)
        if model:
            clauses.append("r.requested_model LIKE ? ESCAPE '\\'")
            params.append(_like_pattern(model))
        if key_id is not None:
            clauses.append("r.key_id=?")
            params.append(key_id)
        if endpoint:
            clauses.append("r.endpoint=?")
            params.append(endpoint)
        if provider:
            clauses.append("r.resolved_provider=?")
            params.append(provider)
        if account_id is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM request_attempts a "
                "WHERE a.request_id = r.request_id AND a.account_id=?)"
            )
            params.append(account_id)
        if error_type:
            clauses.append("r.error_type=?")
            params.append(error_type)
        if from_ts:
            clauses.append("r.created_at >= ?")
            params.append(from_ts)
        if to_ts:
            clauses.append("r.created_at < ?")
            params.append(to_ts)
        if q:
            pattern = _like_pattern(q)
            text_columns = (
                "request_id",
                "requested_model",
                "resolved_model",
                "resolved_provider",
                "key_name",
                "error_type",
                "error_message",
            )
            search = [
                f"r.{column} LIKE ? ESCAPE '\\'" for column in text_columns
            ]
            search.append(
                "EXISTS (SELECT 1 FROM request_attempts a "
                "WHERE a.request_id = r.request_id AND ("
                "a.provider_name LIKE ? ESCAPE '\\' OR "
                "a.account_name LIKE ? ESCAPE '\\' OR "
                "a.error_type LIKE ? ESCAPE '\\' OR "
                "a.error_message LIKE ? ESCAPE '\\'))"
            )
            clauses.append(f"({' OR '.join(search)})")
            params.extend([pattern] * (len(text_columns) + 4))
        return clauses, params

    async def stage_request_ids(
        self,
        *,
        before: str | None = None,
        exclude_pending: bool = False,
        status: str | None = None,
        model: str | None = None,
        key_id: int | None = None,
        endpoint: str | None = None,
        q: str | None = None,
        provider: str | None = None,
        account_id: int | None = None,
        error_type: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> int:
        """Snapshot matching request ids into a temp table for export/purge."""
        clauses, params = self._request_filter_clause(
            status=status,
            model=model,
            key_id=key_id,
            endpoint=endpoint,
            q=q,
            provider=provider,
            account_id=account_id,
            error_type=error_type,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        if before:
            clauses.append("r.created_at < ?")
            params.append(before)
        if exclude_pending:
            clauses.append("r.status <> 'pending'")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        await self._conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _archive_ids "
            "(request_id TEXT PRIMARY KEY)"
        )
        await self._conn.execute("DELETE FROM _archive_ids")
        await self._conn.execute(
            "INSERT OR IGNORE INTO _archive_ids(request_id) "
            f"SELECT r.request_id FROM requests r {where}",
            tuple(params),
        )
        await self._conn.commit()
        row = await self._fetchone("SELECT COUNT(*) AS n FROM _archive_ids")
        return int(row["n"]) if row else 0

    async def iter_staged_requests(
        self, *, include_payloads: bool = True, batch_size: int = 500
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield batches of staged requests with their attempts/payloads."""
        last_id = 0
        while True:
            rows = await self._fetchall(
                "SELECT r.* FROM requests r "
                "JOIN _archive_ids a ON a.request_id = r.request_id "
                "WHERE r.id > ? ORDER BY r.id LIMIT ?",
                (last_id, batch_size),
            )
            if not rows:
                return
            ids = [row["request_id"] for row in rows]
            placeholders = ",".join("?" * len(ids))
            attempts = await self._fetchall(
                "SELECT * FROM request_attempts "
                f"WHERE request_id IN ({placeholders}) "
                "ORDER BY request_id, attempt_n",
                tuple(ids),
            )
            payloads = (
                await self._fetchall(
                    "SELECT * FROM payloads "
                    f"WHERE request_id IN ({placeholders}) ORDER BY request_id, id",
                    tuple(ids),
                )
                if include_payloads
                else []
            )
            attempts_by_request: dict[str, list[dict[str, Any]]] = {}
            for attempt in attempts:
                attempts_by_request.setdefault(attempt["request_id"], []).append(
                    dict(attempt)
                )
            payloads_by_request: dict[str, list[dict[str, Any]]] = {}
            for payload_row in payloads:
                payloads_by_request.setdefault(
                    payload_row["request_id"], []
                ).append(dict(payload_row))
            batch = []
            for row in rows:
                item = dict(row)
                item["attempts"] = attempts_by_request.get(row["request_id"], [])
                item["payloads"] = payloads_by_request.get(row["request_id"], [])
                batch.append(item)
            last_id = int(rows[-1]["id"])
            yield batch

    async def delete_staged_requests(self, batch_size: int = 1000) -> int:
        """Delete every staged request and its child rows. Returns count."""
        total = 0
        while True:
            rows = await self._fetchall(
                "SELECT request_id FROM _archive_ids LIMIT ?", (batch_size,)
            )
            if not rows:
                break
            ids = [row["request_id"] for row in rows]
            placeholders = ",".join("?" * len(ids))
            for table in ("payloads", "request_attempts", "usage_records", "requests"):
                await self._conn.execute(
                    f"DELETE FROM {table} WHERE request_id IN ({placeholders})",
                    tuple(ids),
                )
            await self._conn.execute(
                f"DELETE FROM _archive_ids WHERE request_id IN ({placeholders})",
                tuple(ids),
            )
            await self._conn.commit()
            total += len(ids)
        return total

    async def clear_staged_requests(self) -> None:
        await self._conn.execute("DELETE FROM _archive_ids")
        await self._conn.commit()

    async def vacuum(self) -> None:
        await self._conn.commit()
        await self._conn.execute("VACUUM")
        await self._conn.commit()
        await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await self._conn.commit()

    async def list_request_filter_options(self) -> dict[str, Any]:
        providers = [
            row["resolved_provider"]
            for row in await self._fetchall(
                "SELECT DISTINCT resolved_provider FROM requests "
                "WHERE resolved_provider IS NOT NULL AND resolved_provider <> '' "
                "ORDER BY resolved_provider"
            )
        ]
        endpoints = [
            row["endpoint"]
            for row in await self._fetchall(
                "SELECT DISTINCT endpoint FROM requests "
                "WHERE endpoint IS NOT NULL AND endpoint <> '' ORDER BY endpoint"
            )
        ]
        error_types = [
            row["error_type"]
            for row in await self._fetchall(
                "SELECT DISTINCT error_type FROM requests "
                "WHERE error_type IS NOT NULL AND error_type <> '' ORDER BY error_type"
            )
        ]
        keys = [
            dict(row)
            for row in await self._fetchall(
                "SELECT key_id, MAX(key_name) AS key_name FROM requests "
                "WHERE key_id IS NOT NULL GROUP BY key_id ORDER BY key_name"
            )
        ]
        accounts = [
            dict(row)
            for row in await self._fetchall(
                "SELECT account_id, MAX(account_name) AS account_name "
                "FROM request_attempts WHERE account_id IS NOT NULL "
                "GROUP BY account_id ORDER BY account_name"
            )
        ]
        return {
            "providers": providers,
            "endpoints": endpoints,
            "error_types": error_types,
            "keys": keys,
            "accounts": accounts,
        }

    async def get_request(self, request_id: str) -> dict[str, Any] | None:
        row = await self._fetchone(
            "SELECT * FROM requests WHERE request_id=?", (request_id,)
        )
        if row is None:
            return None
        request = dict(row)
        request["attempts"] = [
            dict(r)
            for r in await self._fetchall(
                "SELECT * FROM request_attempts WHERE request_id=? ORDER BY attempt_n",
                (request_id,),
            )
        ]
        request["payloads"] = [
            dict(r)
            for r in await self._fetchall(
                "SELECT * FROM payloads WHERE request_id=? ORDER BY id", (request_id,)
            )
        ]
        return request

    async def add_usage(
        self,
        *,
        request_id: str,
        provider_id: int | None,
        account_id: int | None,
        key_id: int | None,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
        cost: float,
    ) -> None:
        await self._write(
            "INSERT INTO usage_records(request_id, provider_id, account_id, key_id, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                request_id,
                provider_id,
                account_id,
                key_id,
                model,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_write_tokens,
                cost,
                now_iso(),
            ),
        )

    # ---------------------------------------------------------------------- stats
    async def stats(self) -> dict[str, Any]:
        totals = await self._fetchone(
            "SELECT COUNT(*) AS requests, "
            "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success, "
            "COALESCE(SUM(input_tokens),0) AS input_tokens, "
            "COALESCE(SUM(output_tokens),0) AS output_tokens, "
            "COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens, "
            "COALESCE(SUM(cache_write_tokens),0) AS cache_write_tokens, "
            "COALESCE(SUM(cost),0) AS cost FROM requests"
        )
        today = await self._fetchone(
            "SELECT COUNT(*) AS requests, COALESCE(SUM(cost),0) AS cost, "
            "COALESCE(SUM(input_tokens),0) AS input_tokens, "
            "COALESCE(SUM(output_tokens),0) AS output_tokens, "
            "COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens, "
            "COALESCE(SUM(cache_write_tokens),0) AS cache_write_tokens "
            "FROM requests WHERE date(created_at)=date('now')"
        )
        timeseries = await self._fetchall(
            "SELECT date(created_at) AS day, COUNT(*) AS requests, "
            "COALESCE(SUM(input_tokens),0) AS input_tokens, "
            "COALESCE(SUM(output_tokens),0) AS output_tokens, "
            "COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens, "
            "COALESCE(SUM(cost),0) AS cost "
            "FROM requests WHERE created_at >= datetime('now','-14 days') "
            "GROUP BY date(created_at) ORDER BY day"
        )
        by_provider = await self._fetchall(
            "SELECT COALESCE(resolved_provider,'unknown') AS provider, COUNT(*) AS requests, "
            "COALESCE(SUM(input_tokens),0) AS input_tokens, "
            "COALESCE(SUM(output_tokens),0) AS output_tokens, "
            "COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens, "
            "COALESCE(SUM(cost),0) AS cost FROM requests "
            "GROUP BY resolved_provider ORDER BY requests DESC"
        )
        recent = await self._fetchall(
            "SELECT request_id, created_at, requested_model, resolved_provider, "
            "resolved_model, endpoint, status, http_status, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, cost, duration_ms "
            "FROM requests ORDER BY id DESC LIMIT 10"
        )
        counts = await self._fetchone(
            "SELECT (SELECT COUNT(*) FROM providers) AS providers, "
            "(SELECT COUNT(*) FROM accounts) AS accounts, "
            "(SELECT COUNT(*) FROM combos) AS combos, "
            "(SELECT COUNT(*) FROM keys) AS keys"
        )
        return {
            "totals": dict(totals) if totals else {},
            "today": dict(today) if today else {},
            "timeseries": [dict(row) for row in timeseries],
            "by_provider": [dict(row) for row in by_provider],
            "recent": [dict(row) for row in recent],
            "counts": dict(counts) if counts else {},
        }
