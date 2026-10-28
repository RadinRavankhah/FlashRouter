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
    ) -> str:
        attempt_id = uuid.uuid4().hex
        now = _now()
        async with self._db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO attempts
                (attempt_id, request_id, attempt_n, upstream_model, status_code,
                 duration_ms, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    request_id,
                    attempt_n,
                    upstream_model,
                    status_code,
                    duration_ms,
                    error,
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
