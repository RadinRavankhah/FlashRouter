from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from flashrouter.app import create_app
from flashrouter.config import (
    GatewayConfig,
    ModelConfig,
    ServerConfig,
    Settings,
    UpstreamConfig,
)
from flashrouter.core.contracts import RequestLogSink
from flashrouter.protocols.openai_chat import OpenAIChatAdapter
from flashrouter.routing.models import ConfiguredModelResolver
from flashrouter.services.proxy import ChatCompletionsProxy
from flashrouter.transport.http import HttpxTransport

GATEWAY_KEY = "gw-test-key"
UPSTREAM_KEY = "sk-upstream-test"

Handler = Callable[[httpx.Request], Any]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make_settings(
    tmp_path: Path,
    *,
    models: list[ModelConfig] | None = None,
    headers: dict[str, str] | None = None,
) -> Settings:
    return Settings(
        server=ServerConfig(host="127.0.0.1", port=8787, log_level="warning"),
        gateway=GatewayConfig(api_key=GATEWAY_KEY),
        upstream=UpstreamConfig(
            name="mock-upstream",
            base_url="https://upstream.test/v1",
            api_key=UPSTREAM_KEY,
            headers=headers or {},
            trust_env=False,
        ),
        models=models
        or [ModelConfig(id="coding-fast", upstream_model="real-model", owned_by="mock")],
        data_dir=tmp_path,
        config_path=tmp_path / "config.toml",
    )


def auth_headers(key: str = GATEWAY_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@asynccontextmanager
async def gateway_client(
    settings: Settings,
    handler: Handler,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(settings, http_client=upstream_client)
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway.test",
            ) as client:
                yield client, app
    finally:
        await upstream_client.aclose()


@asynccontextmanager
async def direct_proxy(
    settings: Settings,
    handler: Handler,
    *,
    sink: RequestLogSink | None = None,
) -> AsyncIterator[ChatCompletionsProxy]:
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        yield ChatCompletionsProxy(
            settings,
            ConfiguredModelResolver(settings.models),
            OpenAIChatAdapter(),
            HttpxTransport(upstream_client),
            sink or RecordingSink(),
        )
    finally:
        await upstream_client.aclose()


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, event) -> None:
        self.events.append(dict(event))


class StaticStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk


class ControlledStream(httpx.AsyncByteStream):
    """Yields a first chunk, then waits until the test releases the second."""

    def __init__(
        self,
        first: bytes = b"data: first\n\n",
        second: bytes = b"data: second\n\n",
    ) -> None:
        self.first = first
        self.second = second
        self.release_second = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            yield self.first
            await self.release_second.wait()
            yield self.second
        finally:
            self.closed = True

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)
