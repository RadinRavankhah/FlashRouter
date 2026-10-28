"""Shared httpx transport for upstream requests."""

from __future__ import annotations

import httpx

from flashrouter.config import UpstreamConfig


def create_http_client(upstream: UpstreamConfig) -> httpx.AsyncClient:
    timeout = httpx.Timeout(
        connect=upstream.connect_timeout_seconds,
        read=upstream.read_timeout_seconds,
        write=upstream.read_timeout_seconds,
        pool=upstream.connect_timeout_seconds,
    )
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    return httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        verify=upstream.verify_tls,
        trust_env=upstream.trust_env,
        follow_redirects=upstream.follow_redirects,
        headers={},
    )


class HttpxTransport:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    async def send(self, request: httpx.Request) -> httpx.Response:
        return await self._client.send(request)

    async def stream(self, request: httpx.Request) -> httpx.Response:
        return await self._client.send(request, stream=True)
