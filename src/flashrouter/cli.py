"""Command-line interface for FlashRouter."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import socket
import sqlite3
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn

from flashrouter import __version__
from flashrouter.config import ConfigError, Settings, ensure_data_dirs, load_config
from flashrouter.errors import GatewayError
from flashrouter.logging import configure_logging
from flashrouter.services.archive import (
    export_requests,
    parse_cutoff,
    parse_timestamp,
    purge_requests,
)
from flashrouter.storage.database import Database
from flashrouter.storage.repository import Repository


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flashrouter",
        description="Local-first, OpenAI-compatible LLM router with auto-fallback",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Start the gateway and dashboard")
    run.add_argument("--config", type=Path, help="Path to config.toml")
    run.add_argument("--host", help="Bind address (default 127.0.0.1)")
    run.add_argument("--port", type=int, help="Port (default 20128)")
    run.add_argument(
        "--log-level", choices=["debug", "info", "warning", "error"], help="Log level"
    )

    doctor = sub.add_parser("doctor", help="Inspect configuration and storage")
    doctor.add_argument("--config", type=Path, help="Path to config.toml")
    doctor.add_argument("--probe", action="store_true", help="Probe each provider's /models")

    backup = sub.add_parser("backup", help="Back up the database")
    backup.add_argument("--config", type=Path, help="Path to config.toml")

    restore = sub.add_parser("restore", help="Restore the database from a backup file")
    restore.add_argument("file", type=Path, help="Backup file to restore")
    restore.add_argument("--config", type=Path, help="Path to config.toml")

    reset = sub.add_parser("reset-admin", help="Delete client API keys (and settings)")
    reset.add_argument("--config", type=Path, help="Path to config.toml")
    reset.add_argument(
        "--all", action="store_true", help="Also delete providers, accounts, combos, models"
    )

    open_cmd = sub.add_parser("open", help="Open the dashboard in a browser")
    open_cmd.add_argument("--config", type=Path, help="Path to config.toml")

    requests_cmd = sub.add_parser("requests", help="Export or purge stored requests")
    requests_sub = requests_cmd.add_subparsers(dest="requests_command")

    export_cmd = requests_sub.add_parser("export", help="Export requests to a file")
    _add_request_args(export_cmd, before_required=True)
    export_cmd.add_argument(
        "--format",
        choices=["jsonl", "csv", "both"],
        default="jsonl",
        help="Export format (both writes JSONL and CSV)",
    )
    export_cmd.add_argument(
        "--no-payloads",
        action="store_false",
        dest="include_payloads",
        default=True,
        help="Export metadata only (JSONL)",
    )
    export_cmd.add_argument(
        "--output", type=Path, help="Write the export to this path instead"
    )

    purge_cmd = requests_sub.add_parser(
        "purge", help="Export then permanently delete old requests"
    )
    _add_request_args(purge_cmd, before_required=True)
    purge_cmd.add_argument(
        "--format",
        choices=["jsonl", "csv", "both"],
        default="jsonl",
        help="Archive format (both writes JSONL and CSV)",
    )
    purge_cmd.add_argument(
        "--no-payloads",
        action="store_false",
        dest="include_payloads",
        default=True,
        help="Archive metadata only (JSONL)",
    )
    purge_cmd.add_argument(
        "--dry-run", action="store_true", help="Show how many requests would be deleted"
    )
    purge_cmd.add_argument(
        "--yes", action="store_true", help="Confirm permanent deletion"
    )
    purge_cmd.add_argument(
        "--vacuum", action="store_true", help="VACUUM the database afterwards"
    )
    purge_cmd.add_argument(
        "--output", type=Path, help="Move the archive into this directory"
    )

    sub.add_parser("version", help="Print the version")
    return parser


def _add_request_args(parser: argparse.ArgumentParser, *, before_required: bool) -> None:
    parser.add_argument("--config", type=Path, help="Path to config.toml")
    parser.add_argument(
        "--before",
        required=before_required,
        help="Cutoff date (YYYY-MM-DD, UTC) - requests created before it",
    )
    parser.add_argument("--status", help="Filter by status")
    parser.add_argument("--model", help="Filter by requested model (substring)")
    parser.add_argument("--key-id", type=int, dest="key_id", help="Filter by API key id")
    parser.add_argument("--account-id", type=int, dest="account_id", help="Filter by account id")
    parser.add_argument("--endpoint", help="Filter by API endpoint")
    parser.add_argument("--provider", help="Filter by resolved provider")
    parser.add_argument("--error-type", dest="error_type", help="Filter by error type")
    parser.add_argument("--q", help="Free-text search")
    parser.add_argument("--from", dest="from_date", help="From date (UTC, inclusive)")
    parser.add_argument("--to", dest="to_date", help="To date (UTC, inclusive)")


def _settings(args: argparse.Namespace) -> Settings:
    return load_config(getattr(args, "config", None))


def _dashboard_url(settings: Settings) -> str:
    host = settings.server.host
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    return f"http://{host}:{settings.server.port}"


def _port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


# ------------------------------------------------------------------------- run
def _cmd_run(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if args.host:
        settings.server.host = args.host
    if args.port:
        settings.server.port = args.port
    if args.log_level:
        settings.server.log_level = args.log_level

    configure_logging(settings.server.log_level)
    ensure_data_dirs(settings)

    host = settings.server.host
    port = settings.server.port
    if not _port_available(host, port):
        print(
            f"Port {port} on {host} is already in use. Use --port to choose another port.",
            file=sys.stderr,
        )
        return 1

    from flashrouter.app import create_app

    app = create_app(settings)
    url = _dashboard_url(settings)
    print("FlashRouter")
    print(f"  Dashboard: {url}")
    print(f"  API base:  {url}/v1")
    print(f"  Data:      {settings.data_dir}")
    print(f"\nOpen {url} in your browser to manage providers and keys.")
    print("Press Ctrl+C to stop.")

    try:
        uvicorn.run(app, host=host, port=port, log_level=settings.server.log_level)
    except KeyboardInterrupt:
        pass
    return 0


# ---------------------------------------------------------------------- doctor
def _cmd_doctor(args: argparse.Namespace) -> int:
    settings = _settings(args)
    print(f"Config:        {settings.config_path}")
    print(f"Data dir:      {settings.data_dir}")
    print(f"Database:      {settings.database_path}")
    print(f"Listen:        http://{settings.server.host}:{settings.server.port}")
    print(f"Port free:     {_port_available(settings.server.host, settings.server.port)}")
    print(f"Token saver:   {settings.token_saver}")

    if not settings.database_path.exists():
        print("Database not initialised yet (run `flashrouter run` once).")
        return 0

    async def _inspect() -> dict:
        database = Database(settings.database_path)
        await database.connect()
        await database.migrate()
        repo = Repository(database)
        data = {
            "providers": await repo.list_providers(),
            "accounts": await repo.list_accounts(),
            "combos": await repo.list_combos(),
            "keys": await repo.count_keys(),
        }
        await database.close()
        return data

    data = asyncio.run(_inspect())
    print(f"Providers:     {len(data['providers'])}")
    for provider in data["providers"]:
        print(f"  - {provider['name']} ({provider['base_url']}) enabled={provider['enabled']}")
    print(f"Accounts:      {len(data['accounts'])}")
    print(f"Combos:        {len(data['combos'])}")
    for combo in data["combos"]:
        print(f"  - {combo['name']}: {len(combo['targets'])} target(s)")
    print(f"Client keys:   {data['keys']}")

    if args.probe:
        return _probe(settings)
    return 0


def _probe(settings: Settings) -> int:
    import httpx

    from flashrouter.transport.headers import build_upstream_headers
    from flashrouter.transport.urls import join_url

    async def _run() -> int:
        database = Database(settings.database_path)
        await database.connect()
        await database.migrate()
        repo = Repository(database)
        status = 0
        async with httpx.AsyncClient(timeout=20) as client:
            for provider in await repo.list_providers():
                accounts = await repo.list_accounts(provider["id"])
                secret = accounts[0]["secret"] if accounts else None
                url = join_url(provider["base_url"], "models")
                dialect = (
                    "anthropic"
                    if provider.get("protocol") == "anthropic-messages"
                    else None
                )
                headers = build_upstream_headers(
                    provider.get("headers"), secret, stream=False, dialect=dialect
                )
                try:
                    response = await client.get(url, headers=headers)
                    print(f"  {provider['name']}: {response.status_code} {url}")
                    if response.status_code >= 400:
                        status = 1
                except Exception as exc:  # noqa: BLE001
                    print(f"  {provider['name']}: ERROR {exc}")
                    status = 1
        await database.close()
        return status

    return asyncio.run(_run())


# ---------------------------------------------------------------------- backup
def _cmd_backup(args: argparse.Namespace) -> int:
    settings = _settings(args)
    ensure_data_dirs(settings)
    source = settings.database_path
    if not source.exists():
        print("No database to back up yet.", file=sys.stderr)
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = settings.backups_dir / f"flashrouter-{stamp}.db"
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    print(f"Backed up to {destination}")
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    settings = _settings(args)
    ensure_data_dirs(settings)
    source = Path(args.file)
    if not source.exists():
        print(f"Backup file not found: {source}", file=sys.stderr)
        return 1
    destination = settings.database_path
    if destination.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety = settings.backups_dir / f"pre-restore-{stamp}.db"
        with sqlite3.connect(destination) as src, sqlite3.connect(safety) as dst:
            src.backup(dst)
        print(f"Saved current database to {safety}")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(destination) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    print(f"Restored {destination} from {source}")
    return 0


# ------------------------------------------------------------------ reset-admin
def _cmd_reset_admin(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not settings.database_path.exists():
        print("No database found.", file=sys.stderr)
        return 1
    with sqlite3.connect(settings.database_path) as conn:
        conn.execute("DELETE FROM keys")
        conn.execute("DELETE FROM settings")
        if args.all:
            conn.execute("DELETE FROM combo_targets")
            conn.execute("DELETE FROM combos")
            conn.execute("DELETE FROM models")
            conn.execute("DELETE FROM accounts")
            conn.execute("DELETE FROM providers")
        conn.commit()
    print("Client API keys and settings cleared." + (" All data wiped." if args.all else ""))
    return 0


def _request_filters(args: argparse.Namespace) -> dict:
    return {
        "status": args.status,
        "model": args.model,
        "key_id": args.key_id,
        "endpoint": args.endpoint,
        "q": args.q,
        "provider": args.provider,
        "account_id": args.account_id,
        "error_type": args.error_type,
        "from_ts": parse_timestamp(args.from_date, param="from"),
        "to_ts": parse_timestamp(args.to_date, param="to", shift_days=1),
    }


def _place_archive(path: Path, output: Path | None, *, as_dir: bool) -> Path:
    if output is None:
        return path
    target = output / path.name if as_dir or output.is_dir() else output
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
    return target


def _place_archives(
    result: dict, output: Path | None, *, as_dir: bool
) -> list[Path]:
    files = result.get("files") or [result]
    multiple = len(files) > 1
    if multiple and output is not None:
        output.mkdir(parents=True, exist_ok=True)
    return [
        _place_archive(Path(item["path"]), output, as_dir=as_dir or multiple)
        for item in files
    ]


# --------------------------------------------------------------------- requests
def _cmd_requests(args: argparse.Namespace) -> int:
    if args.requests_command not in ("export", "purge"):
        print(
            "Use 'flashrouter requests export' or 'flashrouter requests purge'.",
            file=sys.stderr,
        )
        return 1
    settings = _settings(args)
    ensure_data_dirs(settings)
    if not settings.database_path.exists():
        print("No database found.", file=sys.stderr)
        return 1

    async def _run() -> int:
        database = Database(settings.database_path)
        await database.connect()
        try:
            await database.migrate()
            repo = Repository(database)
            before = parse_cutoff(args.before)
            filters = _request_filters(args)
            if args.requests_command == "export":
                result = await export_requests(
                    repo,
                    settings.exports_dir,
                    fmt=args.format,
                    include_payloads=args.include_payloads,
                    before=before,
                    filters=filters,
                )
                paths = _place_archives(result, args.output, as_dir=False)
                joined = ", ".join(str(path) for path in paths)
                print(
                    f"Exported {result['exported']} requests to {joined} "
                    f"({result['bytes']} bytes)"
                )
                return 0

            if args.dry_run:
                result = await purge_requests(
                    repo,
                    settings.exports_dir,
                    before=before,
                    fmt=args.format,
                    include_payloads=args.include_payloads,
                    dry_run=True,
                    filters=filters,
                )
                print(f"{result['matched']} requests match. Nothing deleted (--dry-run).")
                return 0

            if not args.yes:
                result = await purge_requests(
                    repo,
                    settings.exports_dir,
                    before=before,
                    fmt=args.format,
                    include_payloads=args.include_payloads,
                    dry_run=True,
                    filters=filters,
                )
                print(
                    f"{result['matched']} requests match. "
                    "Re-run with --yes to archive and delete them."
                )
                return 1

            result = await purge_requests(
                repo,
                settings.exports_dir,
                before=before,
                fmt=args.format,
                include_payloads=args.include_payloads,
                dry_run=False,
                vacuum=args.vacuum,
                filters=filters,
            )
            paths = _place_archives(result, args.output, as_dir=True)
            joined = ", ".join(str(path) for path in paths)
            print(
                f"Exported {result['exported']} then deleted "
                f"{result['deleted']} requests. Archive: {joined}"
            )
            if result["vacuumed"]:
                print("Database vacuumed.")
            return 0
        finally:
            await database.close()

    try:
        return asyncio.run(_run())
    except GatewayError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return 1


def _cmd_open(args: argparse.Namespace) -> int:
    settings = _settings(args)
    url = _dashboard_url(settings)
    print(url)
    webbrowser.open(url)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["run"]
    elif argv[0].startswith("-") and argv[0] not in ("--version", "-h", "--help"):
        argv = ["run", *argv]

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "doctor":
            return _cmd_doctor(args)
        if args.command == "backup":
            return _cmd_backup(args)
        if args.command == "restore":
            return _cmd_restore(args)
        if args.command == "reset-admin":
            return _cmd_reset_admin(args)
        if args.command == "requests":
            return _cmd_requests(args)
        if args.command == "open":
            return _cmd_open(args)
        if args.command == "version":
            print(__version__)
            return 0
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
