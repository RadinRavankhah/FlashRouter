"""Command-line interface for FlashRouter."""

from __future__ import annotations

import argparse
import asyncio
import socket
import sqlite3
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn

from flashrouter import __version__
from flashrouter.config import ConfigError, Settings, ensure_data_dirs, load_config
from flashrouter.logging import configure_logging
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

    sub.add_parser("version", help="Print the version")
    return parser


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
                headers = build_upstream_headers(
                    provider.get("headers"), secret, stream=False
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
