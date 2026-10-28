"""Small interfaces shared by the proxy layers.

The concrete implementations in v0.1 are intentionally minimal. These seams keep
future request logging, routing, and accounting work from rewriting the data path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol

import httpx

from flashrouter.config import ModelConfig


class ProtocolAdapter(Protocol):
    """Translates one client protocol into an upstream protocol."""

    name: str

    def validate_request(self, payload: Any) -> dict[str, Any]: ...

    def is_stream(self, payload: Mapping[str, Any]) -> bool: ...

    def prepare_body(
        self, payload: Mapping[str, Any], upstream_model: str
    ) -> dict[str, Any]: ...

    def chat_path(self) -> str: ...

    def models_path(self) -> str: ...


class UpstreamTransport(Protocol):
    """Sends fully prepared requests to an upstream."""

    async def send(self, request: httpx.Request) -> httpx.Response: ...

    async def stream(self, request: httpx.Request) -> httpx.Response: ...


class RequestLogSink(Protocol):
    """Receives a compact event after each logical request."""

    def record(self, event: Mapping[str, Any]) -> None: ...


class ModelResolver(Protocol):
    """Resolves a client-facing model id to a configured upstream model."""

    def resolve(self, model_id: str) -> ModelConfig: ...

    def list_models(self) -> list[ModelConfig]: ...


class UsageAccountant(Protocol):
    """Observes upstream usage in future releases."""

    def observe(self, event: Mapping[str, Any]) -> None: ...


class NullUsageAccountant:
    def observe(self, event: Mapping[str, Any]) -> None:
        return None


class AsyncByteStream(Protocol):
    def __aiter__(self) -> AsyncIterator[bytes]: ...
