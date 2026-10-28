"""Sanitized upstream diagnostics, primarily for OpenRouter policy errors."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from flashrouter.transport.urls import join_upstream_url

SENSITIVE_HEADERS = {
    "authorization",
    "api-key",
    "cookie",
    "openai-api-key",
    "proxy-authorization",
    "set-cookie",
    "set-cookie2",
    "x-api-key",
}

PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@dataclass(slots=True)
class DiagnosticTarget:
    name: str
    base_url: str
    api_key: str
    model: str


def redact_proxy_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return "<invalid proxy URL>"
    if not parts.scheme or not parts.netloc:
        return value
    if parts.username is None and parts.password is None:
        return value
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    netloc = f"***:***@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def proxy_environment() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in PROXY_ENV_NAMES:
        value = os.getenv(name)
        result[name] = redact_proxy_url(value) if value else None
    return result


def redact_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in headers.items():
        if name.lower() in SENSITIVE_HEADERS:
            result[name] = "<redacted>"
        else:
            result[name] = value
    return result


def request_id_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in headers.items():
        lowered = name.lower()
        if (
            lowered in {"x-request-id", "traceparent"}
            or lowered.startswith("x-openrouter-")
            or lowered.startswith("x-ratelimit-")
            or lowered == "cf-ray"
        ):
            result[name] = value
    return result


def _truncate(text: str, limit: int = 6000) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n<truncated>"


async def probe_target(
    target: DiagnosticTarget,
    *,
    message: str,
    trust_env: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    url = join_upstream_url(target.base_url, "chat/completions")
    body = {
        "model": target.model,
        "messages": [{"role": "user", "content": message}],
        "max_tokens": 16,
    }
    headers = {
        "Authorization": f"Bearer {target.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "FlashRouter-Diagnostics/0.1.0",
    }
    report: dict[str, Any] = {
        "name": target.name,
        "request": {
            "method": "POST",
            "url": url,
            "headers": redact_headers(headers),
            "body": body,
        },
        "environment_proxy_enabled": trust_env,
    }

    started = perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            trust_env=trust_env,
            follow_redirects=False,
            headers={},
        ) as client:
            response = await client.post(url, headers=headers, json=body)
        report["elapsed_ms"] = int((perf_counter() - started) * 1000)
        report["response"] = {
            "status": response.status_code,
            "headers": redact_headers(response.headers),
            "request_ids": request_id_headers(response.headers),
            "body": _truncate(response.text),
        }
    except httpx.HTTPError as exc:
        report["elapsed_ms"] = int((perf_counter() - started) * 1000)
        report["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    return report


async def run_diagnostic(
    targets: list[DiagnosticTarget],
    *,
    message: str,
    trust_env: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    return {
        "environment": {"proxy": proxy_environment(), "trust_env": trust_env},
        "targets": [
            await probe_target(
                target,
                message=message,
                trust_env=trust_env,
                timeout_seconds=timeout_seconds,
            )
            for target in targets
        ],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flashrouter-diagnose",
        description="Compare sanitized direct and gateway requests to an upstream.",
    )
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key", default=os.getenv("OPENROUTER_API_KEY"))
    parser.add_argument("--model", default=os.getenv("OPENROUTER_MODEL"))
    parser.add_argument("--message", default="Reply with the single word: pong")
    parser.add_argument("--via-url", help="Optional gateway/proxy base URL to compare")
    parser.add_argument(
        "--via-api-key",
        default=os.getenv("FLASHROUTER_GATEWAY_API_KEY"),
        help="Gateway API key for --via-url",
    )
    parser.add_argument("--via-model", help="Model name to send through --via-url")
    parser.add_argument("--trust-env", action="store_true")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.api_key:
        parser.error("--api-key or OPENROUTER_API_KEY is required")
    if not args.model:
        parser.error("--model or OPENROUTER_MODEL is required")

    targets = [
        DiagnosticTarget(
            name="direct",
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.model,
        )
    ]
    if args.via_url:
        if not args.via_api_key:
            parser.error("--via-api-key or FLASHROUTER_GATEWAY_API_KEY is required with --via-url")
        targets.append(
            DiagnosticTarget(
                name="via-gateway",
                base_url=args.via_url,
                api_key=args.via_api_key,
                model=args.via_model or args.model,
            )
        )

    report = asyncio.run(
        run_diagnostic(
            targets,
            message=args.message,
            trust_env=args.trust_env,
            timeout_seconds=args.timeout,
        )
    )
    rendered = json.dumps(report, indent=2)
    print(rendered)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"\nReport written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
