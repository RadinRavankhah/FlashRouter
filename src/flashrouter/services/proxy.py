"""Core Chat Completions proxy behavior with dynamic provider resolution."""

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
from flashrouter.errors import (
    invalid_request,
    upstream_connection_error,
    upstream_timeout_error,
)
from flashrouter.logging import get_logger
from flashrouter.storage.repository import RequestRepository
from flashrouter.transport.headers import (
    build_upstream_headers,
    filter_response_headers,
)
from flashrouter.transport.http import HttpxTransport
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
        self._default_transport = transport
        self._request_log = request_log
        self._usage_accountant = usage_accountant
        self._repository = repository
        self._logger = get_logger()
        self._client_cache: dict[str, httpx.AsyncClient] = {}

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

    async def _get_transport_for_provider(
        self,
        provider: dict[str, Any] | None,
    ) -> UpstreamTransport:
        """Get or create an UpstreamTransport for a provider."""
        if provider is None:
            return self._default_transport

        provider_id = provider["id"]
        if provider_id in self._client_cache:
            return HttpxTransport(self._client_cache[provider_id])

        headers = {}
        try:
            import json as _json

            headers = _json.loads(provider.get("headers") or "{}")
        except Exception:
            headers = {}

        client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=provider.get("connect_timeout_seconds") or 10.0,
                read=provider.get("read_timeout_seconds") or 180.0,
                write=provider.get("read_timeout_seconds") or 180.0,
                pool=provider.get("read_timeout_seconds") or 180.0,
            ),
            verify=bool(provider.get("verify_tls", 1)),
            trust_env=bool(provider.get("trust_env", 0)),
            follow_redirects=bool(provider.get("follow_redirects", 0)),
            headers=headers,
        )
        self._client_cache[provider_id] = client
        return HttpxTransport(client)

    def _build_request(
        self,
        body: Mapping[str, Any],
        *,
        stream: bool,
        base_url: str,
        adapter_path: str,
        api_key: str | None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Request:
        url = join_upstream_url(base_url, adapter_path)
        headers = build_upstream_headers(
            self._settings.upstream,
            api_key,
            stream=stream,
        )
        if extra_headers:
            for k, v in extra_headers.items():
                headers[k] = v
        content = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return httpx.Request("POST", url, headers=headers, content=content)

    def _prepare_legacy(
        self,
        payload: Any,
        adapter: ProtocolAdapter | None = None,
    ) -> tuple[str, str, bool, httpx.Request, dict[str, Any] | None, str | None]:
        """Legacy resolution using settings.upstream + ConfiguredModelResolver."""
        use_adapter = adapter if adapter is not None else self._adapter
        body = use_adapter.validate_request(payload)
        requested_model = body["model"]
        model = self._resolver.resolve(requested_model)
        upstream_model = model.upstream_model or model.id
        upstream_body = use_adapter.prepare_body(body, upstream_model)
        stream = use_adapter.is_stream(body)
        request = self._build_request(
            upstream_body,
            stream=stream,
            base_url=self._settings.upstream.base_url,
            adapter_path=use_adapter.chat_path(),
            api_key=self._settings.upstream_api_key(),
        )
        return requested_model, upstream_model, stream, request, None, None

    def _prepare_db(
        self,
        payload: Any,
        resolved: dict[str, Any],
        adapter: ProtocolAdapter | None = None,
    ) -> tuple[str, str, bool, httpx.Request, dict[str, Any] | None, str | None]:
        """DB-backed resolution using provider + credential from alias."""
        use_adapter = adapter if adapter is not None else self._adapter
        body = use_adapter.validate_request(payload)
        requested_model = body["model"]
        upstream_model = resolved.get("upstream_model") or requested_model
        upstream_body = use_adapter.prepare_body(body, upstream_model)
        stream = use_adapter.is_stream(body)

        base_url = resolved.get("base_url", "")
        api_key = resolved.get("secret")
        extra_headers: dict[str, str] = {}
        try:
            import json as _json

            if resolved.get("headers"):
                extra_headers = _json.loads(resolved["headers"])
        except Exception:
            extra_headers = {}

        request = self._build_request(
            upstream_body,
            stream=stream,
            base_url=base_url,
            adapter_path=use_adapter.chat_path(),
            api_key=api_key,
            extra_headers=extra_headers,
        )
        provider = {
            "id": resolved.get("provider_id", ""),
            "base_url": base_url,
            "headers": resolved.get("headers", "{}"),
            "connect_timeout_seconds": resolved.get("connect_timeout_seconds", 10.0),
            "read_timeout_seconds": resolved.get("read_timeout_seconds", 180.0),
            "verify_tls": resolved.get("verify_tls", 1),
            "trust_env": resolved.get("trust_env", 0),
            "follow_redirects": resolved.get("follow_redirects", 0),
        }
        return (
            requested_model,
            upstream_model,
            stream,
            request,
            provider,
            resolved.get("credential_id"),
        )

    async def _prepare(
        self,
        payload: Any,
        adapter: ProtocolAdapter | None = None,
    ) -> tuple[str, str, bool, httpx.Request, dict[str, Any] | None, str | None]:
        """Resolve model: try DB alias first, fall back to legacy settings."""
        use_adapter = adapter if adapter is not None else self._adapter
        body = use_adapter.validate_request(payload)
        requested_model = body["model"]

        if self._repository is not None:
            resolved = await self._repository.resolve_alias(requested_model)
            if resolved:
                return self._prepare_db(payload, resolved, adapter=adapter)

        # Fall back to legacy settings-based resolution.
        if self._settings.upstream.base_url:
            return self._prepare_legacy(payload, adapter=adapter)

        raise invalid_request(
            f"Model '{requested_model}' not configured. Add it via the dashboard.",
            code="model_not_found",
        )

    async def complete(
        self,
        payload: Any,
        request_id: str,
        *,
        model_id: str | None = None,
        adapter: ProtocolAdapter | None = None,
    ) -> Response:
        requested_model, upstream_model, stream, upstream_request, provider, credential_id = (
            await self._prepare(payload, adapter=adapter)
        )
        started = perf_counter()

        if model_id is None:
            model_id = requested_model

        transport = await self._get_transport_for_provider(provider)

        # Persist the outgoing request body.
        await self._persist(
            "add_payload",
            request_id=request_id,
            kind="request_outgoing",
            body_bytes=upstream_request.content,
        )

        try:
            upstream_response = await transport.send(upstream_request)
        except httpx.TimeoutException as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                model_id=model_id or requested_model,
                upstream_model=upstream_model,
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
                credential_id=credential_id,
            )
            raise upstream_timeout_error() from exc
        except httpx.ConnectError as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                model_id=model_id or requested_model,
                upstream_model=upstream_model,
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
                credential_id=credential_id,
            )
            raise upstream_connection_error(f"Upstream connection failed: {exc}") from exc
        except httpx.HTTPError as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                model_id=model_id or requested_model,
                upstream_model=upstream_model,
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
                credential_id=credential_id,
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
                credential_id=credential_id,
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
        adapter: ProtocolAdapter | None = None,
    ) -> Response:
        requested_model, upstream_model, stream, upstream_request, provider, credential_id = (
            await self._prepare(payload, adapter=adapter)
        )
        started = perf_counter()

        transport = await self._get_transport_for_provider(provider)

        # Persist the outgoing request body.
        await self._persist(
            "add_payload",
            request_id=request_id,
            kind="request_outgoing",
            body_bytes=upstream_request.content,
        )

        try:
            upstream_response = await transport.stream(upstream_request)
        except httpx.TimeoutException as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                model_id=model_id or requested_model,
                upstream_model=upstream_model,
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
                credential_id=credential_id,
            )
            raise upstream_timeout_error() from exc
        except httpx.ConnectError as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                model_id=model_id or requested_model,
                upstream_model=upstream_model,
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
                credential_id=credential_id,
            )
            raise upstream_connection_error(f"Upstream connection failed: {exc}") from exc
        except httpx.HTTPError as exc:
            await self._persist(
                "update_request",
                request_id=request_id,
                model_id=model_id or requested_model,
                upstream_model=upstream_model,
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
                credential_id=credential_id,
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
                    credential_id=credential_id,
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
                    credential_id=credential_id,
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
