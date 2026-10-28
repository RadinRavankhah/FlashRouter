"""Request-history repository built on SQLite."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from flashrouter.storage.database import Database


class RequestRepository:
    """Durable request/attempt/payload records for observability."""

    def __init__(self, database: Database) -> None:
        self._db = database

    # -- writes ---------------------------------------------------------

    async def create_request(
        self,
        *,
        request_id: str,
        gateway_key_id: str,
        client_ip: str | None,
        method: str,
        path: str,
        protocol: str,
        mode: str,
        model_id: str,
        upstream_model: str | None,
    ) -> None:
        now = _now()
        async with self._db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO requests
                (request_id, gateway_key_id, client_ip, method, path, protocol, mode,
                 model_id, upstream_model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    gateway_key_id,
                    client_ip,
                    method,
                    path,
                    protocol,
                    mode,
                    model_id,
                    upstream_model,
                    now,
                ),
            )

    async def add_payload(
        self,
        *,
        request_id: str,
        kind: str,
        body_bytes: bytes,
        attempt_id: str | None = None,
    ) -> str:
        payload_id = uuid.uuid4().hex
        now = _now()
        async with self._db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO payloads
                (payload_id, request_id, attempt_id, kind, body_bytes, size_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload_id,
                    request_id,
                    attempt_id,
                    kind,
                    body_bytes,
                    len(body_bytes),
                    now,
                ),
            )
        return payload_id

    async def update_request(
        self,
        *,
        request_id: str,
        mode: str | None = None,
        model_id: str | None = None,
        upstream_model: str | None = None,
        status_code: int | None = None,
        duration_ms: int | None = None,
        ttft_ms: int | None = None,
        completed: bool | None = None,
        error: str | None = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []
        if mode is not None:
            fields.append("mode = ?")
            values.append(mode)
        if model_id is not None:
            fields.append("model_id = ?")
            values.append(model_id)
        if upstream_model is not None:
            fields.append("upstream_model = ?")
            values.append(upstream_model)
        if status_code is not None:
            fields.append("status_code = ?")
            values.append(status_code)
        if duration_ms is not None:
            fields.append("duration_ms = ?")
            values.append(duration_ms)
        if ttft_ms is not None:
            fields.append("ttft_ms = ?")
            values.append(ttft_ms)
        if completed is not None:
            fields.append("completed = ?")
            values.append(1 if completed else 0)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if not fields:
            return
        values.append(request_id)
        async with self._db.transaction() as conn:
            await conn.execute(
                f"UPDATE requests SET {', '.join(fields)} WHERE request_id = ?",
                values,
            )

    async def add_attempt(
        self,
        *,
        request_id: str,
        attempt_n: int,
        upstream_model: str | None,
        status_code: int | None,
        duration_ms: int | None,
        error: str | None,
        credential_id: str | None = None,
    ) -> str:
        attempt_id = uuid.uuid4().hex
        now = _now()
        async with self._db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO attempts
                (attempt_id, request_id, attempt_n, upstream_model, status_code,
                 duration_ms, error, credential_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    request_id,
                    attempt_n,
                    upstream_model,
                    status_code,
                    duration_ms,
                    error,
                    credential_id,
                    now,
                ),
            )
        return attempt_id

    # -- reads ----------------------------------------------------------

    async def get_request(self, request_id: str) -> dict[str, Any] | None:
        async with self._db.connection.execute(
            "SELECT * FROM requests WHERE request_id = ?", (request_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row, strict=False))

    async def list_requests(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        model: str | None = None,
        status: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if model:
            conditions.append("model_id = ?")
            values.append(model)
        if status is not None:
            conditions.append("status_code = ?")
            values.append(status)
        if request_id:
            conditions.append("request_id = ?")
            values.append(request_id)
        if date_from:
            conditions.append("created_at >= ?")
            values.append(date_from)
        if date_to:
            conditions.append("created_at <= ?")
            values.append(date_to)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT * FROM requests {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        values.extend([limit, offset])
        async with self._db.connection.execute(query, values) as cursor:
            rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row, strict=False)) for row in rows]

    async def get_attempts(self, request_id: str) -> list[dict[str, Any]]:
        async with self._db.connection.execute(
            "SELECT * FROM attempts WHERE request_id = ? ORDER BY attempt_n",
            (request_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row, strict=False)) for row in rows]

    async def get_payloads(self, request_id: str) -> list[dict[str, Any]]:
        async with self._db.connection.execute(
            "SELECT * FROM payloads WHERE request_id = ? ORDER BY created_at",
            (request_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row, strict=False)) for row in rows]

    async def get_payload(self, payload_id: str) -> dict[str, Any] | None:
        async with self._db.connection.execute(
            "SELECT * FROM payloads WHERE payload_id = ?", (payload_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row, strict=False))

    # -- stats / health -------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        async with self._db.connection.execute(
            "SELECT COUNT(*) FROM requests"
        ) as cursor:
            total = (await cursor.fetchone())[0]

        async with self._db.connection.execute(
            """
            SELECT COUNT(*) FROM requests
            WHERE completed = 1 AND error IS NULL
            """
        ) as cursor:
            success = (await cursor.fetchone())[0]

        async with self._db.connection.execute(
            "SELECT COUNT(*) FROM requests WHERE completed = 0"
        ) as cursor:
            interrupted = (await cursor.fetchone())[0]

        async with self._db.connection.execute(
            "SELECT COUNT(*) FROM requests WHERE error IS NOT NULL"
        ) as cursor:
            errors = (await cursor.fetchone())[0]

        return {
            "total": total,
            "success": success,
            "interrupted": interrupted,
            "error": errors,
        }

    async def storage_health(self) -> dict[str, Any]:
        import os
        from pathlib import Path

        db_path = Path(self._db.db_path)
        db_size_bytes = db_path.stat().st_size if db_path.exists() else 0
        disk = os.statvfs(str(db_path.parent)) if hasattr(os, "statvfs") else None
        disk_free_bytes = disk.f_bavail * disk.f_frsize if disk else 0
        disk_total_bytes = disk.f_blocks * disk.f_frsize if disk else 0

        return {
            "logging_healthy": True,
            "db_size_mb": round(db_size_bytes / (1024 * 1024), 2),
            "disk_free_gb": round(disk_free_bytes / (1024**3), 2),
            "disk_total_gb": round(disk_total_bytes / (1024**3), 2),
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


# -- providers -----------------------------------------------------------

async def _provider_crud(self):
    pass  # placeholder to keep structure


# Providers

async def create_provider(
    self,
    *,
    provider_id: str,
    name: str,
    base_url: str,
    protocol: str = "openai-chat",
    headers: str | None = None,
    connect_timeout_seconds: float = 10.0,
    read_timeout_seconds: float = 180.0,
    verify_tls: bool = True,
    trust_env: bool = False,
    follow_redirects: bool = False,
    enabled: bool = True,
) -> None:
    now = _now()
    async with self._db.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO providers
            (id, name, base_url, protocol, headers, connect_timeout_seconds,
             read_timeout_seconds, verify_tls, trust_env, follow_redirects, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider_id,
                name,
                base_url,
                protocol,
                headers or "{}",
                connect_timeout_seconds,
                read_timeout_seconds,
                1 if verify_tls else 0,
                1 if trust_env else 0,
                1 if follow_redirects else 0,
                1 if enabled else 0,
                now,
            ),
        )


async def list_providers(self) -> list[dict[str, Any]]:
    async with self._db.connection.execute(
        "SELECT * FROM providers ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    result = []
    for row in rows:
        d = dict(zip(columns, row, strict=False))
        result.append(d)
    return result


async def get_provider(self, provider_id: str) -> dict[str, Any] | None:
    async with self._db.connection.execute(
        "SELECT * FROM providers WHERE id = ?", (provider_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row, strict=False))


async def update_provider(
    self,
    provider_id: str,
    *,
    name: str | None = None,
    base_url: str | None = None,
    protocol: str | None = None,
    headers: str | None = None,
    connect_timeout_seconds: float | None = None,
    read_timeout_seconds: float | None = None,
    verify_tls: bool | None = None,
    trust_env: bool | None = None,
    follow_redirects: bool | None = None,
    enabled: bool | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if base_url is not None:
        fields.append("base_url = ?")
        values.append(base_url)
    if protocol is not None:
        fields.append("protocol = ?")
        values.append(protocol)
    if headers is not None:
        fields.append("headers = ?")
        values.append(headers)
    if connect_timeout_seconds is not None:
        fields.append("connect_timeout_seconds = ?")
        values.append(connect_timeout_seconds)
    if read_timeout_seconds is not None:
        fields.append("read_timeout_seconds = ?")
        values.append(read_timeout_seconds)
    if verify_tls is not None:
        fields.append("verify_tls = ?")
        values.append(1 if verify_tls else 0)
    if trust_env is not None:
        fields.append("trust_env = ?")
        values.append(1 if trust_env else 0)
    if follow_redirects is not None:
        fields.append("follow_redirects = ?")
        values.append(1 if follow_redirects else 0)
    if enabled is not None:
        fields.append("enabled = ?")
        values.append(1 if enabled else 0)
    if not fields:
        return
    values.append(provider_id)
    async with self._db.transaction() as conn:
        await conn.execute(
            f"UPDATE providers SET {', '.join(fields)} WHERE id = ?",
            values,
        )


async def delete_provider(self, provider_id: str) -> None:
    async with self._db.transaction() as conn:
        await conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))


# Provider credentials

async def create_provider_credential(
    self,
    *,
    credential_id: str,
    provider_id: str,
    name: str,
    secret: str,
    enabled: bool = True,
) -> None:
    now = _now()
    async with self._db.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO provider_credentials
            (id, provider_id, name, secret, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (credential_id, provider_id, name, secret, 1 if enabled else 0, now),
        )


async def list_provider_credentials(self) -> list[dict[str, Any]]:
    async with self._db.connection.execute(
        "SELECT * FROM provider_credentials ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in rows]


async def get_provider_credential(self, credential_id: str) -> dict[str, Any] | None:
    async with self._db.connection.execute(
        "SELECT * FROM provider_credentials WHERE id = ?", (credential_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row, strict=False))


async def update_provider_credential(
    self,
    credential_id: str,
    *,
    provider_id: str | None = None,
    name: str | None = None,
    secret: str | None = None,
    enabled: bool | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if provider_id is not None:
        fields.append("provider_id = ?")
        values.append(provider_id)
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if secret is not None:
        fields.append("secret = ?")
        values.append(secret)
    if enabled is not None:
        fields.append("enabled = ?")
        values.append(1 if enabled else 0)
    if not fields:
        return
    values.append(credential_id)
    async with self._db.transaction() as conn:
        await conn.execute(
            f"UPDATE provider_credentials SET {', '.join(fields)} WHERE id = ?",
            values,
        )


async def delete_provider_credential(self, credential_id: str) -> None:
    async with self._db.transaction() as conn:
        await conn.execute("DELETE FROM provider_credentials WHERE id = ?", (credential_id,))


# Gateway keys

async def create_gateway_key(
    self,
    *,
    key_id: str,
    name: str,
    secret: str,
    enabled: bool = True,
) -> None:
    now = _now()
    async with self._db.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO gateway_keys
            (id, name, secret, enabled, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (key_id, name, secret, 1 if enabled else 0, now),
        )


async def list_gateway_keys(self) -> list[dict[str, Any]]:
    async with self._db.connection.execute(
        "SELECT * FROM gateway_keys ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in rows]


async def get_gateway_key(self, key_id: str) -> dict[str, Any] | None:
    async with self._db.connection.execute(
        "SELECT * FROM gateway_keys WHERE id = ?", (key_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row, strict=False))


async def update_gateway_key(
    self,
    key_id: str,
    *,
    name: str | None = None,
    secret: str | None = None,
    enabled: bool | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if secret is not None:
        fields.append("secret = ?")
        values.append(secret)
    if enabled is not None:
        fields.append("enabled = ?")
        values.append(1 if enabled else 0)
    if not fields:
        return
    values.append(key_id)
    async with self._db.transaction() as conn:
        await conn.execute(
            f"UPDATE gateway_keys SET {', '.join(fields)} WHERE id = ?",
            values,
        )


async def delete_gateway_key(self, key_id: str) -> None:
    async with self._db.transaction() as conn:
        await conn.execute("DELETE FROM gateway_keys WHERE id = ?", (key_id,))


# DB models

async def create_db_model(
    self,
    *,
    model_id: str,
    provider_id: str,
    credential_id: str | None,
    upstream_model: str,
    enabled: bool = True,
) -> None:
    now = _now()
    async with self._db.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO db_models
            (id, provider_id, credential_id, upstream_model, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (model_id, provider_id, credential_id, upstream_model, 1 if enabled else 0, now),
        )


async def list_db_models(self) -> list[dict[str, Any]]:
    async with self._db.connection.execute(
        "SELECT * FROM db_models ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in rows]


async def get_db_model(self, model_id: str) -> dict[str, Any] | None:
    async with self._db.connection.execute(
        "SELECT * FROM db_models WHERE id = ?", (model_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row, strict=False))


async def update_db_model(
    self,
    model_id: str,
    *,
    provider_id: str | None = None,
    credential_id: str | None = None,
    upstream_model: str | None = None,
    enabled: bool | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if provider_id is not None:
        fields.append("provider_id = ?")
        values.append(provider_id)
    if credential_id is not None:
        fields.append("credential_id = ?")
        values.append(credential_id)
    if upstream_model is not None:
        fields.append("upstream_model = ?")
        values.append(upstream_model)
    if enabled is not None:
        fields.append("enabled = ?")
        values.append(1 if enabled else 0)
    if not fields:
        return
    values.append(model_id)
    async with self._db.transaction() as conn:
        await conn.execute(
            f"UPDATE db_models SET {', '.join(fields)} WHERE id = ?",
            values,
        )


async def delete_db_model(self, model_id: str) -> None:
    async with self._db.transaction() as conn:
        await conn.execute("DELETE FROM db_models WHERE id = ?", (model_id,))


# Model aliases

async def create_model_alias(
    self,
    *,
    alias_id: str,
    alias: str,
    db_model_id: str,
    enabled: bool = True,
) -> None:
    now = _now()
    async with self._db.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO model_aliases
            (id, alias, db_model_id, enabled, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (alias_id, alias, db_model_id, 1 if enabled else 0, now),
        )


async def list_model_aliases(self) -> list[dict[str, Any]]:
    async with self._db.connection.execute(
        "SELECT * FROM model_aliases ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in rows]


async def get_model_alias(self, alias_id: str) -> dict[str, Any] | None:
    async with self._db.connection.execute(
        "SELECT * FROM model_aliases WHERE id = ?", (alias_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row, strict=False))


async def resolve_alias(self, alias: str) -> dict[str, Any] | None:
    """Resolve a client-facing alias to a db_model with provider and credential info."""
    async with self._db.connection.execute(
        """
        SELECT ma.alias, ma.enabled as alias_enabled,
               dm.id as model_id, dm.upstream_model, dm.enabled as model_enabled,
               p.id as provider_id, p.name as provider_name, p.base_url, p.protocol,
               p.headers, p.connect_timeout_seconds, p.read_timeout_seconds,
               p.verify_tls, p.trust_env, p.follow_redirects, p.enabled as provider_enabled,
               pc.id as credential_id,
               pc.name as credential_name,
               pc.secret,
               pc.enabled as credential_enabled
        FROM model_aliases ma
        JOIN db_models dm ON ma.db_model_id = dm.id
        JOIN providers p ON dm.provider_id = p.id
        LEFT JOIN provider_credentials pc ON dm.credential_id = pc.id
        WHERE ma.alias = ?
        """,
        (alias,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row, strict=False))


async def update_model_alias(
    self,
    alias_id: str,
    *,
    alias: str | None = None,
    db_model_id: str | None = None,
    enabled: bool | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if alias is not None:
        fields.append("alias = ?")
        values.append(alias)
    if db_model_id is not None:
        fields.append("db_model_id = ?")
        values.append(db_model_id)
    if enabled is not None:
        fields.append("enabled = ?")
        values.append(1 if enabled else 0)
    if not fields:
        return
    values.append(alias_id)
    async with self._db.transaction() as conn:
        await conn.execute(
            f"UPDATE model_aliases SET {', '.join(fields)} WHERE id = ?",
            values,
        )


async def delete_model_alias(self, alias_id: str) -> None:
    async with self._db.transaction() as conn:
        await conn.execute("DELETE FROM model_aliases WHERE id = ?", (alias_id,))


# Attach CRUD methods to the class
RequestRepository.create_provider = create_provider
RequestRepository.list_providers = list_providers
RequestRepository.get_provider = get_provider
RequestRepository.update_provider = update_provider
RequestRepository.delete_provider = delete_provider

RequestRepository.create_provider_credential = create_provider_credential
RequestRepository.list_provider_credentials = list_provider_credentials
RequestRepository.get_provider_credential = get_provider_credential
RequestRepository.update_provider_credential = update_provider_credential
RequestRepository.delete_provider_credential = delete_provider_credential

RequestRepository.create_gateway_key = create_gateway_key
RequestRepository.list_gateway_keys = list_gateway_keys
RequestRepository.get_gateway_key = get_gateway_key
RequestRepository.update_gateway_key = update_gateway_key
RequestRepository.delete_gateway_key = delete_gateway_key

RequestRepository.create_db_model = create_db_model
RequestRepository.list_db_models = list_db_models
RequestRepository.get_db_model = get_db_model
RequestRepository.update_db_model = update_db_model
RequestRepository.delete_db_model = delete_db_model

RequestRepository.create_model_alias = create_model_alias
RequestRepository.list_model_aliases = list_model_aliases
RequestRepository.get_model_alias = get_model_alias
RequestRepository.resolve_alias = resolve_alias
RequestRepository.update_model_alias = update_model_alias
RequestRepository.delete_model_alias = delete_model_alias
