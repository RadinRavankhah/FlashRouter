"""Data access layer for FlashRouter."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from flashrouter.storage.database import Database

# Timestamps use SQLite-friendly formatting (space separator, UTC).
TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def now_iso() -> str:
    return datetime.now(UTC).strftime(TIME_FORMAT)


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
    ) -> int:
        now = now_iso()
        return await self._write(
            "INSERT INTO providers(name, preset, base_url, protocol, headers, enabled, "
            "priority, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                name,
                preset,
                base_url,
                protocol,
                json.dumps(headers or {}),
                int(enabled),
                priority,
                now,
                now,
            ),
        )

    async def update_provider(self, provider_id: int, fields: dict[str, Any]) -> bool:
        allowed = {"name", "preset", "base_url", "protocol", "headers", "enabled", "priority"}
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
        source: str = "manual",
        enabled: bool = True,
    ) -> int:
        existing = await self._fetchone(
            "SELECT id FROM models WHERE provider_id=? AND model=?", (provider_id, model)
        )
        if existing:
            await self._write(
                "UPDATE models SET display_name=?, price_in=?, price_out=?, "
                "price_cache_in=?, source=?, enabled=? WHERE id=?",
                (
                    display_name,
                    price_in,
                    price_out,
                    price_cache_in,
                    source,
                    int(enabled),
                    existing["id"],
                ),
            )
            return int(existing["id"])
        return await self._write(
            "INSERT INTO models(provider_id, model, display_name, price_in, price_out, "
            "price_cache_in, source, enabled, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                provider_id,
                model,
                display_name,
                price_in,
                price_out,
                price_cache_in,
                source,
                int(enabled),
                now_iso(),
            ),
        )

    async def ensure_model(
        self, *, provider_id: int, model: str, source: str = "discover"
    ) -> int:
        """Insert a discovered model without overwriting existing pricing."""
        existing = await self._fetchone(
            "SELECT id FROM models WHERE provider_id=? AND model=?", (provider_id, model)
        )
        if existing:
            return int(existing["id"])
        return await self._write(
            "INSERT INTO models(provider_id, model, source, created_at) VALUES (?,?,?,?)",
            (provider_id, model, source, now_iso()),
        )

    async def update_model_pricing(
        self,
        model_id: int,
        *,
        price_in: float,
        price_out: float,
        price_cache_in: float | None,
    ) -> bool:
        changed = await self._write(
            "UPDATE models SET price_in=?, price_out=?, price_cache_in=? WHERE id=?",
            (price_in, price_out, price_cache_in, model_id),
        )
        return changed > 0

    async def get_model_price(
        self, provider_id: int, model: str
    ) -> tuple[float, float, float | None]:
        row = await self._fetchone(
            "SELECT price_in, price_out, price_cache_in FROM models "
            "WHERE provider_id=? AND model=?",
            (provider_id, model),
        )
        if row is None:
            return (0.0, 0.0, None)
        cache_price = row["price_cache_in"]
        return (
            float(row["price_in"]),
            float(row["price_out"]),
            float(cache_price) if cache_price is not None else None,
        )

    async def models_by_name(self, model: str) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT m.model, p.id AS provider_id, p.name AS provider_name, "
            "p.base_url, p.protocol, p.headers, p.enabled AS provider_enabled, "
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
            "p.enabled AS provider_enabled "
            "FROM combo_targets t JOIN providers p ON p.id=t.provider_id "
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
    ) -> dict[str, Any]:
        token = token or ("fr-" + secrets.token_urlsafe(32))
        key_id = await self._write(
            "INSERT INTO keys(name, token, enabled, allowed_combos, created_at) "
            "VALUES (?,?,?,?,?)",
            (name, token, int(enabled), json.dumps(allowed_combos or []), now_iso()),
        )
        return {"id": key_id, "name": name, "token": token}

    async def update_key(self, key_id: int, fields: dict[str, Any]) -> bool:
        allowed = {"name", "enabled", "allowed_combos", "token"}
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
    ) -> None:
        await self._write(
            "INSERT INTO requests(request_id, created_at, key_id, key_name, "
            "requested_model, stream) VALUES (?,?,?,?,?,?)",
            (request_id, now_iso(), key_id, key_name, requested_model, int(stream)),
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
            # Never let best-effort payload logging break a request.
            pass

    async def list_requests(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        model: str | None = None,
        key_id: int | None = None,
    ) -> dict[str, Any]:
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if model:
            clauses.append("requested_model=?")
            params.append(model)
        if key_id is not None:
            clauses.append("key_id=?")
            params.append(key_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total_row = await self._fetchone(
            f"SELECT COUNT(*) AS n FROM requests {where}", tuple(params)
        )
        rows = await self._fetchall(
            f"SELECT * FROM requests {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            tuple(params) + (limit, offset),
        )
        return {
            "total": int(total_row["n"]) if total_row else 0,
            "items": [dict(row) for row in rows],
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
            "resolved_model, status, http_status, input_tokens, output_tokens, "
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
