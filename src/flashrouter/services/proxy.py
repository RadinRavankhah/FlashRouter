"""Core Chat Completions proxy behavior."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from time import perf_counter
from typing import Any

import httpx
from starlette.responses import Response, StreamingResponse

from flashrouter.config import Settings
from flashrouter.core.contracts import (
    ModelResolver,
    ProtocolAdapter,
    RequestLogSink,
    UpstreamTransport,
    UsageAccountant,
)
from flashrouter.errors import upstream_connection_error, upstream_timeout_error
from flashrouter.logging import get_logger
from flashrouter.transport.headers import (
    build_upstream_headers,
    filter_response_headers,
)
from flashrouter.transport.urls import join_upstream_url


class ChatCompletionsProxy:
    def __init__(
        self,
        settings: Settings,
        resolver: ModelResolver,
        adapter: ProtocolAdapter,
        transport: UpstreamTransport,
        request_log: RequestLogSink,
        usage_accountant: UsageAccountant | None = None,
    ) -> None:
        self._settings = settings
        self._resolver = resolver
        self._adapter = adapter
        self._transport = transport
        self._request_log = request_log
        self._usage_accountant = usage_accountant
        self._logger = get_logger()

    def _record(self, event: Mapping[str, Any]) -> None:
        try:
            self._request_log.record(event)
        except Exception:
            self._logger.exception("request_log_failed request_id=%s", event.get("request_id"))

    def _build_request(self, body: Mapping[str, Any], *, stream: bool) -> httpx.Request:
        url = join_upstream_url(
            self._settings.upstream.base_url,
            self._adapter.chat_path(),
        )
        headers = build_upstream_headers(
            self._settings.upstream,
            self._settings.upstream_api_key(),
            stream=stream,
        )
        content = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return httpx.Request("POST", url, headers=headers, content=content)

    def _prepare(
        self,
        payload: Any,
    ) -> tuple[str, str, bool, httpx.Request]:
        body = self._adapter.validate_request(payload)
        requested_model = body["model"]
        model = self._resolver.resolve(requested_model)
        upstream_model = model.upstream_model or model.id
        upstream_body = self._adapter.prepare_body(body, upstream_model)
        stream = self._adapter.is_stream(body)
        request = self._build_request(upstream_body, stream=stream)
        return requested_model, upstream_model, stream, request

    async def complete(self, payload: Any, request_id: str) -> Response:
        requested_model, upstream_model, _, upstream_request = self._prepare(payload)
        started = perf_counter()

        try:
            upstream_response = await self._transport.send(upstream_request)
        except httpx.TimeoutException as exc:
            self._record_error(request_id, requested_model, exc, 504)
            raise upstream_timeout_error() from exc
        except httpx.ConnectError as exc:
            self._record_error(request_id, requested_model, exc, 502)
            raise upstream_connection_error(f"Upstream connection failed: {exc}") from exc
        except httpx.HTTPError as exc:
            self._record_error(request_id, requested_model, exc, 502)
            raise upstream_connection_error(f"Upstream request failed: {exc}") from exc

        try:
            duration_ms = int((perf_counter() - started) * 1000)
            headers = filter_response_headers(upstream_response.headers, streaming=False)
            self._record(
                {
                    "request_id": request_id,
                    "mode": "complete",
                    "model": requested_model,
                    "upstream_model": upstream_model,
                    "status": upstream_response.status_code,
                    "duration_ms": duration_ms,
                }
            )
            if self._usage_accountant is not None:
                self._usage_accountant.observe(
                    {"request_id": request_id, "body": upstream_response.content}
                )
            return Response(
                content=upstream_response.content,
                status_code=upstream_response.status_code,
                headers=headers,
            )
        finally:
            await upstream_response.aclose()

    async def stream(self, payload: Any, request_id: str) -> Response:
        requested_model, upstream_model, _, upstream_request = self._prepare(payload)
        started = perf_counter()

        try:
            upstream_response = await self._transport.stream(upstream_request)
        except httpx.TimeoutException as exc:
            self._record_error(request_id, requested_model, exc, 504)
            raise upstream_timeout_error() from exc
        except httpx.ConnectError as exc:
            self._record_error(request_id, requested_model, exc, 502)
            raise upstream_connection_error(f"Upstream connection failed: {exc}") from exc
        except httpx.HTTPError as exc:
            self._record_error(request_id, requested_model, exc, 502)
            raise upstream_connection_error(f"Upstream request failed: {exc}") from exc

        if not upstream_response.is_success:
            try:
                body = await upstream_response.aread()
                headers = filter_response_headers(upstream_response.headers, streaming=False)
                self._record(
                    {
                        "request_id": request_id,
                        "mode": "stream",
                        "model": requested_model,
                        "upstream_model": upstream_model,
                        "status": upstream_response.status_code,
                        "duration_ms": int((perf_counter() - started) * 1000),
                    }
                )
                return Response(
                    content=body,
                    status_code=upstream_response.status_code,
                    headers=headers,
                )
            finally:
                await upstream_response.aclose()

        headers = filter_response_headers(upstream_response.headers, streaming=True)
        media_type = upstream_response.headers.get("content-type")

        async def iterator() -> AsyncIterator[bytes]:
            completed = False
            error: str | None = None
            try:
                async for chunk in upstream_response.aiter_raw():
                    yield chunk
                completed = True
            except Exception as exc:
                error = str(exc)
                self._logger.warning(
                    "stream_failed request_id=%s error=%s", request_id, exc
                )
                raise
            finally:
                await upstream_response.aclose()
                self._record(
                    {
                        "request_id": request_id,
                        "mode": "stream",
                        "model": requested_model,
                        "upstream_model": upstream_model,
                        "status": upstream_response.status_code,
                        "duration_ms": int((perf_counter() - started) * 1000),
                        "completed": completed,
                        "error": error,
                    }
                )

        return StreamingResponse(
            iterator(),
            status_code=upstream_response.status_code,
            headers=headers,
            media_type=media_type,
        )

    def _record_error(
        self,
        request_id: str,
        requested_model: str,
        exc: Exception,
        status_code: int,
    ) -> None:
        self._record(
            {
                "request_id": request_id,
                "mode": "error",
                "model": requested_model,
                "status": status_code,
                "error": type(exc).__name__,
            }
        )
