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
from flashrouter.storage.repository import RequestRepository
from flashrouter.transport.headers import (
    build_upstream_headers,
    filter_response_headers,
)
from flashrouter.transport.urls import join_upstream_url


def _reconstruct_openai_stream(raw_chunks: list[bytes]) -> dict[str, Any]:
    """Parse OpenAI Chat Completions SSE chunks into a reconstructed response body."""
    content_parts: list[str] = []
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    chunk_id: str | None = None
    model: str | None = None
    created: int | None = None

    for raw in raw_chunks:
        text = raw.decode("utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                continue
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if chunk_id is None:
                chunk_id = chunk.get("id")
            if model is None:
                model = chunk.get("model")
            if created is None:
                created = chunk.get("created")
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content"):
                    content_parts.append(delta["content"])
                for tc in delta.get("tool_calls", []) or []:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_by_index:
                        func = tc.get("function", {}) or {}
                        tool_calls_by_index[idx] = {
                            "index": idx,
                            "id": tc.get("id"),
                            "type": tc.get("type", "function"),
                            "function": {
                                "name": func.get("name"),
                                "arguments": func.get("arguments", ""),
                            },
                        }
                    existing = tool_calls_by_index[idx]
                    func = tc.get("function", {}) or {}
                    if func.get("name"):
                        existing["function"]["name"] = func["name"]
                    if func.get("arguments"):
                        existing["function"]["arguments"] += func["arguments"]
                fr = choice.get("finish_reason")
                if fr:
                    finish_reason = fr
            if chunk.get("usage"):
                usage = chunk["usage"]

    choices: list[dict[str, Any]] = [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "".join(content_parts),
            },
            "finish_reason": finish_reason,
        }
    ]
    if tool_calls_by_index:
        choices[0]["message"]["tool_calls"] = [
            tool_calls_by_index[i] for i in sorted(tool_calls_by_index)
        ]

    return {
        "id": chunk_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": choices,
        "usage": usage,
    }


class ChatCompletionsProxy:
    def __init__(
        self,
        settings: Settings,
        resolver: ModelResolver,
        adapter: ProtocolAdapter,
        transport: UpstreamTransport,
        request_log: RequestLogSink,
        usage_accountant: UsageAccountant | None = None,
        repository: RequestRepository | None = None,
    ) -> None:
        self._settings = settings
        self._resolver = resolver
        self._adapter = adapter
        self._transport = transport
        self._request_log = request_log
        self._usage_accountant = usage_accountant
        self._repository = repository
        self._logger = get_logger()

    def _record(self, event: Mapping[str, Any]) -> None:
        try:
            self._request_log.record(event)
        except Exception:
            self._logger.exception("request_log_failed request_id=%s", event.get("request_id"))

    async def _persist(
        self,
        operation: str,
        *,
        request_id: str,
        **kwargs: Any,
    ) -> None:
        if self._repository is None:
            return
        try:
            if operation == "add_payload":
                await self._repository.add_payload(request_id=request_id, **kwargs)
            elif operation == "update_request":
                await self._repository.update_request(request_id=request_id, **kwargs)
            elif operation == "add_attempt":
                await self._repository.add_attempt(request_id=request_id, **kwargs)
        except Exception:
            self._logger.exception(
                "storage_persist_failed operation=%s request_id=%s", operation, request_id
            )

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

    async def complete(
        self,
        payload: Any,
        request_id: str,
        *,
        model_id: str | None = None,
    ) -> Response:
        requested_model, upstream_model, _, upstream_request = self._prepare(payload)
        started = perf_counter()

        # Persist the outgoing request body.
        await self._persist(
            "add_payload",
            request_id=request_id,
            kind="request_outgoing",
            body_bytes=upstream_request.content,
        )

        try:
            upstream_response = await self._transport.send(upstream_request)
        except httpx.TimeoutException as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                status_code=504,
                duration_ms=int((perf_counter() - started) * 1000),
                completed=True,
                error="upstream_timeout",
            )
            await self._persist(
                "add_attempt",
                request_id=request_id,
                attempt_n=1,
                upstream_model=upstream_model,
                status_code=None,
                duration_ms=None,
                error="upstream_timeout",
            )
            raise upstream_timeout_error() from exc
        except httpx.ConnectError as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                status_code=502,
                duration_ms=int((perf_counter() - started) * 1000),
                completed=True,
                error="upstream_connection_failed",
            )
            await self._persist(
                "add_attempt",
                request_id=request_id,
                attempt_n=1,
                upstream_model=upstream_model,
                status_code=None,
                duration_ms=None,
                error="upstream_connection_failed",
            )
            raise upstream_connection_error(f"Upstream connection failed: {exc}") from exc
        except httpx.HTTPError as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                status_code=502,
                duration_ms=int((perf_counter() - started) * 1000),
                completed=True,
                error="upstream_request_failed",
            )
            await self._persist(
                "add_attempt",
                request_id=request_id,
                attempt_n=1,
                upstream_model=upstream_model,
                status_code=None,
                duration_ms=None,
                error="upstream_request_failed",
            )
            raise upstream_connection_error(f"Upstream request failed: {exc}") from exc

        try:
            duration_ms = int((perf_counter() - started) * 1000)
            headers = filter_response_headers(upstream_response.headers, streaming=False)
            body = upstream_response.content

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

            await self._persist(
                "update_request",
                request_id=request_id,
                model_id=model_id or requested_model,
                upstream_model=upstream_model,
                status_code=upstream_response.status_code,
                duration_ms=duration_ms,
                completed=True,
                error=None,
            )
            await self._persist(
                "add_payload",
                request_id=request_id,
                kind="response_client",
                body_bytes=body,
            )
            await self._persist(
                "add_attempt",
                request_id=request_id,
                attempt_n=1,
                upstream_model=upstream_model,
                status_code=upstream_response.status_code,
                duration_ms=duration_ms,
                error=None,
            )
            if self._usage_accountant is not None:
                self._usage_accountant.observe(
                    {"request_id": request_id, "body": body}
                )
            return Response(
                content=body,
                status_code=upstream_response.status_code,
                headers=headers,
            )
        finally:
            await upstream_response.aclose()

    async def stream(
        self,
        payload: Any,
        request_id: str,
        *,
        model_id: str | None = None,
    ) -> Response:
        requested_model, upstream_model, _, upstream_request = self._prepare(payload)
        started = perf_counter()

        # Persist the outgoing request body.
        await self._persist(
            "add_payload",
            request_id=request_id,
            kind="request_outgoing",
            body_bytes=upstream_request.content,
        )

        try:
            upstream_response = await self._transport.stream(upstream_request)
        except httpx.TimeoutException as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                status_code=504,
                duration_ms=int((perf_counter() - started) * 1000),
                completed=True,
                error="upstream_timeout",
            )
            await self._persist(
                "add_attempt",
                request_id=request_id,
                attempt_n=1,
                upstream_model=upstream_model,
                status_code=None,
                duration_ms=None,
                error="upstream_timeout",
            )
            raise upstream_timeout_error() from exc
        except httpx.ConnectError as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                status_code=502,
                duration_ms=int((perf_counter() - started) * 1000),
                completed=True,
                error="upstream_connection_failed",
            )
            await self._persist(
                "add_attempt",
                request_id=request_id,
                attempt_n=1,
                upstream_model=upstream_model,
                status_code=None,
                duration_ms=None,
                error="upstream_connection_failed",
            )
            raise upstream_connection_error(f"Upstream connection failed: {exc}") from exc
        except httpx.HTTPError as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                status_code=502,
                duration_ms=int((perf_counter() - started) * 1000),
                completed=True,
                error="upstream_request_failed",
            )
            await self._persist(
                "add_attempt",
                request_id=request_id,
                attempt_n=1,
                upstream_model=upstream_model,
                status_code=None,
                duration_ms=None,
                error="upstream_request_failed",
            )
            raise upstream_connection_error(f"Upstream request failed: {exc}") from exc

        if not upstream_response.is_success:
            try:
                body = await upstream_response.aread()
                headers = filter_response_headers(upstream_response.headers, streaming=False)
                duration_ms = int((perf_counter() - started) * 1000)

                self._record(
                    {
                        "request_id": request_id,
                        "mode": "stream",
                        "model": requested_model,
                        "upstream_model": upstream_model,
                        "status": upstream_response.status_code,
                        "duration_ms": duration_ms,
                    }
                )
                await self._persist(
                    "update_request",
                    request_id=request_id,
                    model_id=model_id or requested_model,
                    upstream_model=upstream_model,
                    status_code=upstream_response.status_code,
                    duration_ms=duration_ms,
                    completed=True,
                    error=None,
                )
                await self._persist(
                    "add_payload",
                    request_id=request_id,
                    kind="response_client",
                    body_bytes=body,
                )
                await self._persist(
                    "add_attempt",
                    request_id=request_id,
                    attempt_n=1,
                    upstream_model=upstream_model,
                    status_code=upstream_response.status_code,
                    duration_ms=duration_ms,
                    error=None,
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

        raw_chunks: list[bytes] = []
        ttft_ms: int | None = None

        async def iterator() -> AsyncIterator[bytes]:
            nonlocal ttft_ms
            completed = False
            error: str | None = None
            try:
                async for chunk in upstream_response.aiter_raw():
                    if ttft_ms is None:
                        ttft_ms = int((perf_counter() - started) * 1000)
                    raw_chunks.append(chunk)
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
                duration_ms = int((perf_counter() - started) * 1000)

                self._record(
                    {
                        "request_id": request_id,
                        "mode": "stream",
                        "model": requested_model,
                        "upstream_model": upstream_model,
                        "status": upstream_response.status_code,
                        "duration_ms": duration_ms,
                        "completed": completed,
                        "error": error,
                    }
                )

                await self._persist(
                    "update_request",
                    request_id=request_id,
                    model_id=model_id or requested_model,
                    upstream_model=upstream_model,
                    status_code=upstream_response.status_code,
                    duration_ms=duration_ms,
                    ttft_ms=ttft_ms,
                    completed=completed,
                    error=error,
                )
                reconstructed = _reconstruct_openai_stream(raw_chunks)
                await self._persist(
                    "add_payload",
                    request_id=request_id,
                    kind="response_client",
                    body_bytes=json.dumps(reconstructed, ensure_ascii=False).encode("utf-8"),
                )
                await self._persist(
                    "add_attempt",
                    request_id=request_id,
                    attempt_n=1,
                    upstream_model=upstream_model,
                    status_code=upstream_response.status_code,
                    duration_ms=duration_ms,
                    error=error,
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
