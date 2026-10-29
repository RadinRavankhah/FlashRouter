"""Shared httpx transport for upstream requests."""

from __future__ import annotations

import httpx

from flashrouter.config import Settings


def create_client(settings: Settings) -> httpx.AsyncClient:
    timeout = httpx.Timeout(
        connect=settings.connect_timeout,
        read=settings.request_timeout,
        write=settings.request_timeout,
        pool=settings.connect_timeout,
    )
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=40)
    return httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        verify=True,
        trust_env=False,
        follow_redirects=False,
        headers={},
    )
