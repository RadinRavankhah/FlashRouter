"""SQLite connection management and migration runner."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import aiosqlite

from flashrouter.logging import get_logger
from flashrouter.storage.migrations import MIGRATIONS, SCHEMA_VERSION

logger = get_logger()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database is not connected")
        return self._conn

    async def _open(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.commit()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await self._open()
        if await self._is_legacy():
            await self.close()
            archived = self._archive()
            logger.warning(
                "legacy_database_archived path=%s archived=%s", self.path, archived
            )
            await self._open()

    async def _table_exists(self, name: str) -> bool:
        async with self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def _user_table_count(self) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) AS n FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ) as cursor:
            row = await cursor.fetchone()
            return int(row["n"]) if row else 0

    async def _is_legacy(self) -> bool:
        """Detect a pre-FlashRouter-v2 database that must be recreated.

        The earlier prototype used different table shapes under the same file
        name. Its ``schema_migrations`` versions also collide with ours, so we
        use a sentinel table that only the current schema creates.
        """
        if await self._table_exists("flashrouter_meta"):
            return False
        if await self._table_exists("combo_targets"):
            return False
        return await self._user_table_count() > 0

    def _archive(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archived = self.path.with_name(f"{self.path.stem}.legacy-{stamp}{self.path.suffix}")
        try:
            self.path.rename(archived)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(self.path) + suffix)
                if sidecar.exists():
                    sidecar.replace(Path(str(archived) + suffix))
        except OSError as exc:  # pragma: no cover - depends on external locks
            raise RuntimeError(
                f"Found an incompatible legacy database at {self.path} but could not "
                f"archive it ({exc}). Close any other FlashRouter instances and retry."
            ) from exc
        return archived

    async def migrate(self) -> None:
        conn = self.conn
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS flashrouter_meta ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        await conn.execute(
            "INSERT INTO flashrouter_meta(key, value) VALUES ('schema', 'flashrouter') "
            "ON CONFLICT(key) DO NOTHING"
        )
        await conn.commit()

        async with conn.execute("SELECT version FROM schema_migrations") as cursor:
            applied = {row["version"] for row in await cursor.fetchall()}
        for version in range(1, SCHEMA_VERSION + 1):
            if version in applied:
                continue
            script = MIGRATIONS.get(version)
            if script is None:
                raise RuntimeError(f"missing migration for version {version}")
            await conn.executescript(script)
            await conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) "
                "VALUES (?, datetime('now'))",
                (version,),
            )
            await conn.commit()
        # Recover rows left pending by an abrupt shutdown.
        await conn.execute(
            "UPDATE requests SET status='interrupted' WHERE status='pending'"
        )
        await conn.execute(
            "UPDATE request_attempts SET status='interrupted' WHERE status='pending'"
        )
        await conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
