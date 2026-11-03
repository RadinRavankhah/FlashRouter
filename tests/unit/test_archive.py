from __future__ import annotations

import asyncio
import csv
import json
from contextlib import asynccontextmanager
from pathlib import Path

from flashrouter.services.archive import export_requests, purge_requests
from flashrouter.storage.database import Database
from flashrouter.storage.repository import Repository

OLD_CUTOFF = "2026-02-01 00:00:00.000000"


@asynccontextmanager
async def _repo(tmp_path: Path):
    database = Database(tmp_path / "flashrouter.db")
    await database.connect()
    await database.migrate()
    try:
        yield database, Repository(database)
    finally:
        await database.close()


async def _seed(repo: Repository, database: Database) -> None:
    rows = [
        {
            "request_id": "req-old-success",
            "model": "gpt-4o",
            "provider": "OpenAI",
            "status": "success",
            "created_at": "2026-01-01 10:00:00.000000",
        },
        {
            "request_id": "req-old-error",
            "model": "gpt-4o-mini",
            "provider": "DeepSeek",
            "status": "error",
            "created_at": "2026-01-02 10:00:00.000000",
        },
        {
            "request_id": "req-old-pending",
            "model": "gpt-4o",
            "provider": "OpenAI",
            "status": "pending",
            "created_at": "2026-01-03 10:00:00.000000",
        },
        {
            "request_id": "req-new-success",
            "model": "gpt-4o",
            "provider": "OpenAI",
            "status": "success",
            "created_at": "2026-03-01 10:00:00.000000",
        },
    ]
    for row in rows:
        request_id = row["request_id"]
        await repo.create_request(
            request_id=request_id,
            requested_model=row["model"],
            key_id=1,
            key_name="key",
            stream=False,
        )
        await repo.add_attempt(
            request_id=request_id,
            attempt_n=1,
            provider_id=1,
            provider_name=row["provider"],
            account_id=1,
            account_name="acct",
            model=row["model"],
        )
        await repo.add_payload(
            request_id=request_id, kind="incoming", body='{"prompt":"hello"}'
        )
        await repo.add_payload(
            request_id=request_id,
            kind="response_raw",
            body='data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
        )
        await repo.add_usage(
            request_id=request_id,
            provider_id=1,
            account_id=1,
            key_id=1,
            model=row["model"],
            input_tokens=10,
            output_tokens=5,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost=0.25,
        )
        if row["status"] != "pending":
            await repo.finish_request(
                request_id,
                {
                    "resolved_provider": row["provider"],
                    "resolved_model": row["model"],
                    "status": row["status"],
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cost": 0.25,
                    "attempts": 1,
                },
            )
        await database.conn.execute(
            "UPDATE requests SET created_at=? WHERE request_id=?",
            (row["created_at"], request_id),
        )
    await database.conn.commit()


def test_export_jsonl_is_full_fidelity(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            result = await export_requests(
                repo,
                tmp_path / "exports",
                fmt="jsonl",
                include_payloads=True,
                before=OLD_CUTOFF,
            )
            assert result["matched"] == 3
            assert result["exported"] == 3
            path = Path(result["path"])
            lines = path.read_text(encoding="utf-8").splitlines()
            assert len(lines) == 3
            records = [json.loads(line) for line in lines]
            assert {record["request"]["request_id"] for record in records} == {
                "req-old-success",
                "req-old-error",
                "req-old-pending",
            }
            for record in records:
                assert record["payloads_included"] is True
                assert len(record["attempts"]) == 1
                assert {payload["kind"] for payload in record["payloads"]} == {
                    "incoming",
                    "response_raw",
                }

    asyncio.run(run())


def test_export_csv_is_flat(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            result = await export_requests(
                repo,
                tmp_path / "exports",
                fmt="csv",
                include_payloads=False,
                before=OLD_CUTOFF,
            )
            path = Path(result["path"])
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            assert len(rows) == 3
            assert rows[0]["attempts_count"] == "1"
            assert rows[0]["payload_count"] == "0"
            assert "payloads" not in rows[0]

    asyncio.run(run())


def test_export_both_writes_jsonl_and_csv(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            result = await export_requests(
                repo,
                tmp_path / "exports",
                fmt="both",
                include_payloads=True,
                before=OLD_CUTOFF,
            )
            assert result["exported"] == 3
            assert [item["format"] for item in result["files"]] == ["jsonl", "csv"]
            assert len(list((tmp_path / "exports").glob("*.jsonl"))) == 1
            assert len(list((tmp_path / "exports").glob("*.csv"))) == 1
            assert all(Path(item["path"]).is_file() for item in result["files"])

    asyncio.run(run())


def test_purge_dry_run_does_not_delete(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            result = await purge_requests(
                repo,
                tmp_path / "exports",
                before=OLD_CUTOFF,
                dry_run=True,
            )
            assert result["matched"] == 2
            assert (await repo.list_requests())["total"] == 4
            assert (await repo.stats())["totals"]["requests"] == 4

    asyncio.run(run())


def test_purge_deletes_exact_exported_set(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            result = await purge_requests(
                repo,
                tmp_path / "exports",
                before=OLD_CUTOFF,
                fmt="both",
                include_payloads=True,
                dry_run=False,
            )
            assert result["matched"] == 2
            assert result["exported"] == 2
            assert result["deleted"] == 2
            assert [item["format"] for item in result["files"]] == ["jsonl", "csv"]
            assert {Path(item["path"]).suffix for item in result["files"]} == {
                ".jsonl",
                ".csv",
            }

            remaining = await repo.list_requests()
            assert {item["request_id"] for item in remaining["items"]} == {
                "req-old-pending",
                "req-new-success",
            }
            assert (await repo.stats())["totals"]["requests"] == 2

            async with database.conn.execute(
                "SELECT request_id FROM request_attempts"
            ) as cursor:
                attempt_ids = {row["request_id"] for row in await cursor.fetchall()}
            async with database.conn.execute(
                "SELECT request_id FROM payloads"
            ) as cursor:
                payload_ids = {row["request_id"] for row in await cursor.fetchall()}
            async with database.conn.execute(
                "SELECT request_id FROM usage_records"
            ) as cursor:
                usage_ids = {row["request_id"] for row in await cursor.fetchall()}
            assert "req-old-success" not in attempt_ids
            assert "req-old-error" not in payload_ids
            assert "req-old-success" not in usage_ids
            assert "req-new-success" in usage_ids

            archive = Path(result["path"]).read_text(encoding="utf-8")
            assert "req-old-success" in archive
            assert "req-new-success" not in archive

            csv_path = next(
                Path(item["path"]) for item in result["files"] if item["format"] == "csv"
            )
            csv_text = csv_path.read_text(encoding="utf-8")
            assert "req-old-success" in csv_text
            assert "req-new-success" not in csv_text

    asyncio.run(run())


def test_purge_respects_filters(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            result = await purge_requests(
                repo,
                tmp_path / "exports",
                before=OLD_CUTOFF,
                dry_run=False,
                filters={"provider": "OpenAI"},
            )
            assert result["deleted"] == 1
            remaining = await repo.list_requests()
            assert "req-old-success" not in {
                item["request_id"] for item in remaining["items"]
            }
            assert "req-old-error" in {
                item["request_id"] for item in remaining["items"]
            }

    asyncio.run(run())


def test_cutoff_is_exclusive(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            await _seed(repo, database)
            result = await purge_requests(
                repo,
                tmp_path / "exports",
                before="2026-01-02 10:00:00.000000",
                dry_run=True,
            )
            assert result["matched"] == 1

    asyncio.run(run())


def test_export_keeps_large_payloads_intact(tmp_path: Path):
    async def run() -> None:
        async with _repo(tmp_path) as (database, repo):
            request_id = "req-large"
            await repo.create_request(
                request_id=request_id,
                requested_model="m",
                key_id=None,
                key_name=None,
                stream=False,
            )
            big = "x" * 300_000
            await repo.add_payload(request_id=request_id, kind="incoming", body=big)
            await repo.finish_request(request_id, {"status": "success"})

            result = await export_requests(
                repo,
                tmp_path / "exports",
                fmt="jsonl",
                include_payloads=True,
            )
            path = Path(result["path"])
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            assert record["payloads"][0]["body"] == big

    asyncio.run(run())
