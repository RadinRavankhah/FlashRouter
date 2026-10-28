"""Command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

import httpx
import uvicorn

from flashrouter import __version__
from flashrouter.app import create_app
from flashrouter.config import (
    ConfigError,
    Settings,
    ensure_data_dirs,
    load_config,
    mask_secret,
)
from flashrouter.transport.headers import build_upstream_headers
from flashrouter.transport.urls import join_upstream_url


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flashrouter",
        description="Local OpenAI-compatible gateway",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="Start the gateway")
    run.add_argument("--config", type=Path, help="Path to config.toml")
    run.add_argument("--host", help="Override the configured bind address")
    run.add_argument("--port", type=int, help="Override the configured port")
    run.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        help="Override the configured log level",
    )

    doctor = subparsers.add_parser("doctor", help="Validate configuration and data directories")
    doctor.add_argument("--config", type=Path, help="Path to config.toml")
    doctor.add_argument(
        "--probe",
        action="store_true",
        help="Make a non-billable GET request to the upstream models endpoint",
    )
    return parser


def _load_or_report(path: Path | None) -> Settings | None:
    try:
        return load_config(path)
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return None


def _check_writable(settings: Settings) -> bool:
    try:
        ensure_data_dirs(settings)
        with tempfile.NamedTemporaryFile(
            dir=settings.data_dir,
            prefix=".flashrouter-write-test-",
            delete=True,
        ):
            pass
    except OSError as exc:
        print(f"Data directory is not writable: {settings.data_dir} ({exc})", file=sys.stderr)
        return False
    return True


async def _probe_upstream(settings: Settings) -> int:
    url = join_upstream_url(settings.upstream.base_url, "models")
    headers = build_upstream_headers(
        settings.upstream,
        settings.upstream_api_key(),
        stream=False,
    )
    headers["Accept"] = "application/json"
    try:
        async with httpx.AsyncClient(
            timeout=settings.upstream.read_timeout_seconds,
            verify=settings.upstream.verify_tls,
            trust_env=settings.upstream.trust_env,
            follow_redirects=settings.upstream.follow_redirects,
            headers={},
        ) as client:
            response = await client.get(url, headers=headers)
        print(f"Upstream probe: {response.status_code} {url}")
        if response.status_code >= 400:
            print(response.text[:1000])
            return 1
        return 0
    except httpx.HTTPError as exc:
        print(f"Upstream probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _run_doctor(args: argparse.Namespace) -> int:
    settings = _load_or_report(args.config)
    if settings is None:
        return 2

    print(f"Config: {settings.config_path}")
    print(f"Data directory: {settings.data_dir}")
    print(f"Server: http://{settings.server.host}:{settings.server.port}")
    print(f"Gateway key: {mask_secret(settings.gateway_api_key())}")
    print(f"Upstream: {settings.upstream.name} ({settings.upstream.base_url})")
    print(f"Upstream key: {mask_secret(settings.upstream_api_key())}")
    print("Models:")
    for model in settings.models:
        print(f"  {model.id} -> {model.upstream_model}")

    if not _check_writable(settings):
        return 1

    print("Data directory is writable.")
    if args.probe:
        return asyncio.run(_probe_upstream(settings))
    return 0


def _run_server(args: argparse.Namespace) -> int:
    settings = _load_or_report(args.config)
    if settings is None:
        return 2

    if args.host:
        settings.server.host = args.host
    if args.port:
        settings.server.port = args.port
    if args.log_level:
        settings.server.log_level = args.log_level

    app = create_app(settings)
    print(f"FlashRouter listening at http://{settings.server.host}:{settings.server.port}/v1")
    uvicorn.run(
        app,
        host=settings.server.host,
        port=settings.server.port,
        log_level=settings.server.log_level,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return _run_server(args)
    if args.command == "doctor":
        return _run_doctor(args)

    parser.print_help()
    return 0
