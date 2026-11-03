"""Export and purge of stored requests.

Archive flow deliberately exports first and only deletes the exact ids that
were written to disk. The staged id snapshot lives in a per-connection SQLite
temp table so a request that completes mid-operation can never be deleted
without having been exported.
"""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from flashrouter.errors import bad_request
from flashrouter.logging import get_logger
from flashrouter.storage.repository import TIME_FORMAT, Repository

logger = get_logger()

_ARCHIVE_LOCK = asyncio.Lock()

REQUEST_COLUMNS = [
    "id",
    "request_id",
    "created_at",
    "finished_at",
    "key_id",
    "key_name",
    "requested_model",
    "resolved_provider",
    "resolved_model",
    "stream",
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
    "endpoint",
]

FILTER_KEYS = (
    "status",
    "model",
    "key_id",
    "endpoint",
    "q",
    "provider",
    "account_id",
    "error_type",
    "from_ts",
    "to_ts",
)


def _parse_datetime(value: str, param: str) -> datetime:
    text = value.strip()
    try:
        if len(text) == 10:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise bad_request("Invalid timestamp", param=param) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_timestamp(
    value: str | None, *, param: str, shift_days: int = 0
) -> str | None:
    if value is None or not value.strip():
        return None
    parsed = _parse_datetime(value, param) + timedelta(days=shift_days)
    return parsed.strftime(TIME_FORMAT)


def parse_cutoff(value: str | None) -> str:
    if value is None or not value.strip():
        raise bad_request("A cutoff date is required", param="before")
    parsed = _parse_datetime(value, "before")
    if parsed > datetime.now(UTC):
        raise bad_request("Cutoff date must not be in the future", param="before")
    return parsed.strftime(TIME_FORMAT)


def clean_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: value
        for key, value in (filters or {}).items()
        if key in FILTER_KEYS and value is not None
    }


def new_export_path(exports_dir: Path, fmt: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return exports_dir / f"requests-{stamp}-{uuid4().hex[:6]}.{fmt}"


def formats_for(fmt: str) -> tuple[str, ...]:
    if fmt == "both":
        return ("jsonl", "csv")
    if fmt not in ("jsonl", "csv"):
        raise bad_request("Invalid export format", param="format")
    return (fmt,)


async def _write_staged(
    repo: Repository, path: Path, fmt: str, include_payloads: bool
) -> dict[str, int]:
    count = 0
    if fmt == "csv":
        columns = [*REQUEST_COLUMNS, "attempts_count", "payload_count"]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            async for batch in repo.iter_staged_requests(
                include_payloads=include_payloads
            ):
                for item in batch:
                    row = {column: item.get(column) for column in REQUEST_COLUMNS}
                    row["attempts_count"] = len(item["attempts"])
                    row["payload_count"] = len(item["payloads"])
                    writer.writerow(row)
                    count += 1
    else:
        with path.open("w", encoding="utf-8", newline="") as handle:
            async for batch in repo.iter_staged_requests(
                include_payloads=include_payloads
            ):
                for item in batch:
                    record = {
                        "request": {
                            key: value
                            for key, value in item.items()
                            if key not in ("attempts", "payloads")
                        },
                        "attempts": item["attempts"],
                        "payloads": item["payloads"],
                        "payloads_included": include_payloads,
                    }
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1
    return {"count": count, "bytes": path.stat().st_size if path.exists() else 0}


async def _write_staged_formats(
    repo: Repository,
    exports_dir: Path,
    formats: tuple[str, ...],
    include_payloads: bool,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for fmt in formats:
        path = new_export_path(exports_dir, fmt)
        stats = await _write_staged(repo, path, fmt, include_payloads)
        files.append(
            {
                "format": fmt,
                "file": path.name,
                "path": str(path),
                "bytes": stats["bytes"],
                "count": stats["count"],
            }
        )
    return files


async def export_requests(
    repo: Repository,
    exports_dir: Path,
    *,
    fmt: str = "jsonl",
    include_payloads: bool = True,
    before: str | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export matching requests without deleting them."""
    formats = formats_for(fmt)
    exports_dir.mkdir(parents=True, exist_ok=True)
    async with _ARCHIVE_LOCK:
        matched = await repo.stage_request_ids(
            before=before,
            exclude_pending=False,
            **clean_filters(filters),
        )
        try:
            files = await _write_staged_formats(
                repo, exports_dir, formats, include_payloads
            )
        finally:
            await repo.clear_staged_requests()
    primary = files[0]
    return {
        "matched": matched,
        "exported": primary["count"],
        "bytes": sum(item["bytes"] for item in files),
        "format": fmt,
        "file": primary["file"],
        "path": primary["path"],
        "files": files,
    }


async def purge_requests(
    repo: Repository,
    exports_dir: Path,
    *,
    before: str,
    fmt: str = "jsonl",
    include_payloads: bool = True,
    dry_run: bool = True,
    vacuum: bool = False,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export matching requests, then delete exactly what was exported."""
    formats = formats_for(fmt)
    cleaned = clean_filters(filters)
    if dry_run:
        async with _ARCHIVE_LOCK:
            matched = await repo.stage_request_ids(
                before=before,
                exclude_pending=True,
                **cleaned,
            )
            await repo.clear_staged_requests()
        return {
            "matched": matched,
            "before": before,
            "format": fmt,
            "dry_run": True,
        }

    exports_dir.mkdir(parents=True, exist_ok=True)
    async with _ARCHIVE_LOCK:
        matched = await repo.stage_request_ids(
            before=before,
            exclude_pending=True,
            **cleaned,
        )
        try:
            files = await _write_staged_formats(
                repo, exports_dir, formats, include_payloads
            )
        except Exception:
            await repo.clear_staged_requests()
            raise
        deleted = await repo.delete_staged_requests()

    vacuumed = False
    if vacuum and deleted:
        try:
            await repo.vacuum()
            vacuumed = True
        except Exception:
            logger.warning("archive_vacuum_failed", exc_info=True)

    primary = files[0]
    return {
        "matched": matched,
        "exported": primary["count"],
        "deleted": deleted,
        "format": fmt,
        "bytes": sum(item["bytes"] for item in files),
        "file": primary["file"],
        "path": primary["path"],
        "files": files,
        "vacuumed": vacuumed,
        "dry_run": False,
    }
