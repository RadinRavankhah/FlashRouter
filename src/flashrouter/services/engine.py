"""Request orchestration: routing, fallback, streaming, logging, usage."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

import anyio
import httpx
from starlette.responses import Response, StreamingResponse

from flashrouter.config import Settings
from flashrouter.errors import (
    GatewayError,
    forbidden,
    no_available_upstream,
    upstream_error,
)
from flashrouter.logging import get_logger
from flashrouter.routing.engine import Candidate, Router, order_accounts
from flashrouter.savers.rtk import apply_token_saver
from flashrouter.services.caching import (
    CacheDecision,
    apply_cache_markers,
    apply_prompt_cache_key,
    resolve_cache_decision,
)
from flashrouter.services.usage import (
    Usage,
    estimate_cost,
    extract_usage,
    merge_usage,
    usage_from_sse_line,
)
from flashrouter.storage.repository import Repository
from flashrouter.transport.headers import (
    build_upstream_headers,
    filter_response_headers,
)
from flashrouter.transport.urls import join_url

PAYLOAD_LIMIT = 200_000
STREAM_CAPTURE_LIMIT = 65_536
_READ_CHUNK = 65_536


def _cache_key_rejected(text: str) -> bool:
    lowered = text.lower()
    if "prompt_cache_key" in lowered:
        return True
    return ("unknown" in lowered or "unrecognized" in lowered or "extra" in lowered) and (
        "parameter" in lowered or "field" in lowered
    )


def _dump(value: Any, limit: int = PAYLOAD_LIMIT) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > limit:
        text = text[:limit] + "...(truncated)"
    return text


def _classify(status: int) -> tuple[bool, bool, str]:
    """Return (retryable, cooldown_account, error_type) for an HTTP status."""
    if status == 429:
        return (True, True, "rate_limit")
    if status in (401, 403):
        return (True, True, "auth_error")
    if status == 402:
        return (True, True, "quota_exceeded")
    if status in (408, 504):
        return (True, False, "timeout")
    if status >= 500:
        return (True, False, "upstream_error")
    if status >= 400:
        return (False, False, "invalid_request")
    return (False, False, "ok")


def _upstream_message(text: str, dialect: str | None, status: int) -> str:
    """Extract a human-readable message from an upstream error body."""
    if not text:
        return f"Upstream returned HTTP {status}"
    if dialect == "anthropic":
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return error["message"][:1000]
    return text[:1000]


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text") or content.get("content")
        return text if isinstance(text, str) else ""
    return ""


def _affinity_key(body: dict[str, Any], model: str) -> str | None:
    """Stable conversation key for cache-aware account pinning."""
    explicit = body.get("session_id") or body.get("prompt_cache_key")
    if isinstance(explicit, str) and explicit.strip():
        return "s:" + explicit.strip()[:256]

    parts: list[list[str]] = []
    system = body.get("system")
    if system:
        parts.append(["system", _content_text(system)])

    messages = body.get("messages")
    if not isinstance(messages, list):
        messages = body.get("input") if isinstance(body.get("input"), list) else []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        if role in {"system", "developer"}:
            if not parts:
                parts.append(["system", _content_text(message.get("content"))])
            continue
        parts.append([role, _content_text(message.get("content"))])
        break

    if not parts:
        return None
    blob = json.dumps([model, parts], ensure_ascii=False, sort_keys=True)
    return "h:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class _SseAccumulator:
    """Best-effort incremental SSE parser for usage and assistant text.

    Handles both OpenAI ``choices[].delta`` streams and Anthropic Messages
    events (``message_start``, ``content_block_delta``, ``message_delta``).
    """

    def __init__(self) -> None:
        self._buffer = ""
        self.text = ""
        self.usage: Usage = Usage()
        self.finish_reason: str | None = None
        self.stream_error: str | None = None
        self._truncated = False

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk.decode("utf-8", errors="ignore")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        usage = usage_from_sse_line(line)
        if usage:
            self.usage = merge_usage(self.usage, usage)
        stripped = line.strip()
        if not stripped.startswith("data:"):
            return
        data = stripped[len("data:") :].strip()
        if not data or data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        self._handle_openai(payload)
        self._handle_anthropic(payload)

    def _append_text(self, text: str) -> None:
        if not text or self._truncated:
            return
        self.text += text
        if len(self.text) >= STREAM_CAPTURE_LIMIT:
            self._truncated = True

    def _handle_openai(self, payload: dict[str, Any]) -> None:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        choice = choices[0]
        if not isinstance(choice, dict):
            return
        if choice.get("finish_reason"):
            self.finish_reason = str(choice["finish_reason"])
        delta = choice.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            self._append_text(delta["content"])

    def _handle_anthropic(self, payload: dict[str, Any]) -> None:
        event_type = payload.get("type")
        if event_type == "message_start":
            message = payload.get("message")
            if isinstance(message, dict):
                self.usage = merge_usage(self.usage, extract_usage(message))
                if message.get("stop_reason"):
                    self.finish_reason = str(message["stop_reason"])
        elif event_type == "content_block_delta":
            delta = payload.get("delta")
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = delta.get("text")
                if isinstance(text, str):
                    self._append_text(text)
        elif event_type == "message_delta":
            delta = payload.get("delta")
            if isinstance(delta, dict) and delta.get("stop_reason"):
                self.finish_reason = str(delta["stop_reason"])
            if payload.get("usage") is not None:
                self.usage = merge_usage(self.usage, extract_usage(payload))
        elif event_type == "error":
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                self.stream_error = str(error["message"])
            else:
                self.stream_error = "Upstream stream error"



class Engine:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        router: Router,
        client: httpx.AsyncClient,
    ) -> None:
        self._settings = settings
        self._repo = repository
        self._router = router
        self._client = client
        self._logger = get_logger()
        self._rr: dict[int, int] = {}
        self._affinity: dict[str, tuple[float, int, int]] = {}
        self._cache_key_unsupported: set[int] = set()

    # ------------------------------------------------------------------ public
    async def handle(
        self,
        *,
        body: dict[str, Any],
        key: dict[str, Any] | None,
        request_id: str,
        endpoint: str = "chat/completions",
        stream: bool = False,
        token_saver: bool | None = None,
        dialect: str | None = None,
        incoming_headers: dict[str, str] | None = None,
        query: str = "",
        record_usage: bool = True,
        cache_override: str | None = None,
    ) -> Response:
        started = time.perf_counter()
        requested_model = str(body.get("model", "") or "")
        key_id = key["id"] if key else None
        key_name = key["name"] if key else None
        affinity_key = _affinity_key(body, requested_model)

        await self._repo.create_request(
            request_id=request_id,
            requested_model=requested_model,
            key_id=key_id,
            key_name=key_name,
            stream=stream,
            endpoint=endpoint,
        )
        await self._repo.add_payload(request_id=request_id, kind="incoming", body=_dump(body))

        if key and key.get("allowed_combos"):
            allowed = key["allowed_combos"]
            if requested_model not in allowed:
                exc = forbidden(
                    f"This API key is not allowed to use model '{requested_model}'"
                )
                await self._finalize_error(request_id, exc, started, attempts=0)
                raise exc

        try:
            candidates = await self._router.resolve(requested_model)
        except GatewayError as exc:
            await self._finalize_error(request_id, exc, started, attempts=0)
            raise

        attempts = 0
        last_error: GatewayError | None = None
        current_attempt_id: int | None = None

        try:
            for candidate in candidates:
                cache_decision = resolve_cache_decision(
                    endpoint=endpoint,
                    provider={
                        "protocol": candidate.protocol,
                        "cache_markers": candidate.cache_markers,
                        "cache_ttl": candidate.cache_ttl,
                    },
                    key=key,
                    override=cache_override,
                )
                eligible = await self._repo.eligible_accounts(candidate.provider_id)
                if not eligible:
                    continue
                counter = self._rr.get(candidate.provider_id, 0)
                self._rr[candidate.provider_id] = counter + 1
                accounts = order_accounts(eligible, counter)
                if cache_decision.active:
                    accounts = self._pin_account(
                        accounts, candidate.provider_id, affinity_key
                    )

                for account in accounts:
                    attempts += 1
                    current_attempt_id = await self._repo.add_attempt(
                        request_id=request_id,
                        attempt_n=attempts,
                        provider_id=candidate.provider_id,
                        provider_name=candidate.provider_name,
                        account_id=account["id"],
                        account_name=account["name"],
                        model=candidate.model,
                    )
                    try:
                        outcome = await self._attempt(
                            candidate=candidate,
                            account=account,
                            body=body,
                            endpoint=endpoint,
                            stream=stream,
                            request_id=request_id,
                            attempt_n=attempts,
                            attempt_id=current_attempt_id,
                            started=started,
                            key_id=key_id,
                            token_saver=token_saver,
                            dialect=dialect,
                            incoming_headers=incoming_headers,
                            query=query,
                            record_usage=record_usage,
                            cache_decision=cache_decision,
                            affinity_key=affinity_key,
                        )
                    except GatewayError as exc:
                        last_error = exc
                        await self._repo.finish_attempt(
                            current_attempt_id,
                            {
                                "status": "error",
                                "error_type": exc.type,
                                "error_message": exc.message,
                                "http_status": exc.status_code,
                            },
                        )
                        current_attempt_id = None
                        if exc.status_code in (400, 404, 422):
                            await self._finalize_error(request_id, exc, started, attempts)
                            raise
                        continue
                    except httpx.HTTPError as exc:
                        # Transport failures happen before anything reaches the
                        # client, so they are safe to fall back from.
                        timed_out = isinstance(exc, httpx.TimeoutException)
                        status = 504 if timed_out else 502
                        message = f"{type(exc).__name__}: {exc}"[:1000]
                        await self._repo.finish_attempt(
                            current_attempt_id,
                            {
                                "status": "error",
                                "error_type": "timeout" if timed_out else "connection_error",
                                "error_message": message,
                                "http_status": status,
                            },
                        )
                        current_attempt_id = None
                        last_error = upstream_error(status, message)
                        continue
                    current_attempt_id = None
                    if outcome is not None:
                        return outcome
        except asyncio.CancelledError:
            await self._finalize_interrupted(
                request_id, current_attempt_id, started, attempts
            )
            raise
        except GatewayError:
            # Already finalized at the point it was raised.
            raise
        except Exception as exc:
            await self._finalize_error(
                request_id,
                upstream_error(500, f"Internal gateway error: {exc}"),
                started,
                attempts,
            )
            raise

        exc = last_error or no_available_upstream(requested_model)
        await self._finalize_error(request_id, exc, started, attempts)
        raise exc

    # ----------------------------------------------------------------- attempts
    async def _attempt(
        self,
        *,
        candidate: Candidate,
        account: dict[str, Any],
        body: dict[str, Any],
        endpoint: str,
        stream: bool,
        request_id: str,
        attempt_n: int,
        attempt_id: int,
        started: float,
        key_id: int | None,
        token_saver: bool | None,
        dialect: str | None,
        incoming_headers: dict[str, str] | None,
        query: str,
        record_usage: bool,
        cache_decision: CacheDecision,
        affinity_key: str | None = None,
    ) -> Response | None:
        outbound = dict(body)
        outbound["model"] = candidate.model
        saver_enabled = (
            token_saver if token_saver is not None else await self._token_saver_enabled()
        )
        if (
            endpoint == "chat/completions"
            and saver_enabled
            and not cache_decision.inject
        ):
            outbound = apply_token_saver(outbound)
        outbound = apply_cache_markers(
            outbound, endpoint=endpoint, decision=cache_decision
        )
        outbound = apply_prompt_cache_key(
            outbound, affinity_key=affinity_key, decision=cache_decision
        )
        cache_key_added = (
            "prompt_cache_key" in outbound and "prompt_cache_key" not in body
        )
        if (
            cache_key_added
            and candidate.provider_id in self._cache_key_unsupported
        ):
            outbound.pop("prompt_cache_key", None)
            cache_key_added = False

        await self._repo.add_payload(
            request_id=request_id,
            attempt_n=attempt_n,
            kind="outgoing",
            body=_dump(outbound),
        )

        url = join_url(candidate.base_url, endpoint, query)
        headers = build_upstream_headers(
            candidate.headers,
            account.get("secret"),
            stream=stream,
            dialect=dialect,
            incoming=incoming_headers,
        )

        def build_request(payload: dict[str, Any]) -> httpx.Request:
            try:
                return httpx.Request(
                    "POST",
                    url,
                    headers=headers,
                    content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                )
            except (TypeError, ValueError) as exc:
                raise upstream_error(502, f"Could not encode request: {exc}") from exc

        async def send_with_fallback(
            payload: dict[str, Any],
        ) -> tuple[httpx.Response, str | None]:
            request = build_request(payload)
            response = await self._client.send(request, stream=stream)
            if response.status_code != 400 or not cache_key_added:
                return response, None
            if stream:
                text = (await response.aread()).decode("utf-8", errors="replace")
                await response.aclose()
            else:
                text = response.content.decode("utf-8", errors="replace")
            if not _cache_key_rejected(text):
                return response, text
            self._cache_key_unsupported.add(candidate.provider_id)
            payload.pop("prompt_cache_key", None)
            await self._repo.add_payload(
                request_id=request_id,
                attempt_n=attempt_n,
                kind="outgoing",
                body=_dump(payload),
            )
            return await self._client.send(build_request(payload), stream=stream), None

        price_in, price_out, price_cache_in, price_cache_write = (
            await self._repo.get_model_price(candidate.provider_id, candidate.model)
        )
        cache_pin = cache_decision.active

        response, error_text = await send_with_fallback(outbound)
        if response.status_code >= 400:
            if error_text is None:
                if stream:
                    error_text = (await response.aread()).decode(
                        "utf-8", errors="replace"
                    )
                    await response.aclose()
                else:
                    error_text = response.content.decode("utf-8", errors="replace")
            await self._handle_http_error(
                response.status_code, error_text, candidate, account, attempt_id, dialect
            )
            return None
        if cache_pin and affinity_key:
            self._remember_affinity(
                affinity_key,
                candidate.provider_id,
                account["id"],
                cache_decision.affinity_ttl,
            )

        if stream:
            return self._stream_response(
                response=response,
                candidate=candidate,
                account=account,
                request_id=request_id,
                attempt_id=attempt_id,
                attempt_n=attempt_n,
                started=started,
                key_id=key_id,
                price_in=price_in,
                price_out=price_out,
                price_cache_in=price_cache_in,
                price_cache_write=price_cache_write,
                record_usage=record_usage,
            )

        content = response.content
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            payload = {}
        usage = extract_usage(payload)
        cost = estimate_cost(
            price_in=price_in,
            price_out=price_out,
            price_cache_in=price_cache_in,
            price_cache_write=price_cache_write,
            usage=usage,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        await self._repo.add_payload(
            request_id=request_id, attempt_n=attempt_n, kind="response", body=_dump(payload)
        )
        await self._repo.finish_attempt(
            attempt_id,
            {
                "status": "success",
                "http_status": response.status_code,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "cache_write_tokens": usage.cache_write_tokens,
                "cost": cost,
            },
        )
        if record_usage:
            await self._record_usage(
                request_id=request_id,
                candidate=candidate,
                account=account,
                key_id=key_id,
                usage=usage,
                cost=cost,
            )
        await self._repo.finish_request(
            request_id,
            {
                "resolved_provider": candidate.provider_name,
                "resolved_model": candidate.model,
                "status": "success",
                "http_status": response.status_code,
                "duration_ms": duration_ms,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "cache_write_tokens": usage.cache_write_tokens,
                "cost": cost,
                "attempts": attempt_n,
            },
        )
        self._logger.info(
            "request_ok id=%s provider=%s model=%s tokens=%s/%s cache_read=%s ms=%s",
            request_id,
            candidate.provider_name,
            candidate.model,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            duration_ms,
        )
        return Response(
            content=content,
            status_code=response.status_code,
            headers=filter_response_headers(response.headers, streaming=False),
            media_type=response.headers.get("content-type", "application/json"),
        )

    async def _handle_http_error(
        self,
        status: int,
        text: str,
        candidate: Candidate,
        account: dict[str, Any],
        attempt_id: int,
        dialect: str | None = None,
    ) -> None:
        retryable, cooldown, error_type = _classify(status)
        message = _upstream_message(text, dialect, status)
        if cooldown:
            await self._repo.cooldown_account(
                account["id"], int(account.get("cooldown_seconds", 60)), message
            )
        await self._repo.finish_attempt(
            attempt_id,
            {
                "status": "error",
                "http_status": status,
                "error_type": error_type,
                "error_message": message,
                "retry_reason": "retryable" if retryable else "fatal",
            },
        )
        if not retryable:
            raise upstream_error(status, message)

    # ------------------------------------------------------------------ stream
    def _stream_response(
        self,
        *,
        response: httpx.Response,
        candidate: Candidate,
        account: dict[str, Any],
        request_id: str,
        attempt_id: int,
        attempt_n: int,
        started: float,
        key_id: int | None,
        price_in: float,
        price_out: float,
        price_cache_in: float | None,
        price_cache_write: float | None = None,
        record_usage: bool = True,
    ) -> StreamingResponse:
        async def iterator():
            accumulator = _SseAccumulator()
            first_byte_at: float | None = None
            status = "success"
            error_type: str | None = None
            error_message: str | None = None
            try:
                async for chunk in response.aiter_raw():
                    if first_byte_at is None:
                        first_byte_at = time.perf_counter()
                    accumulator.feed(chunk)
                    yield chunk
            except httpx.HTTPError as exc:
                status = "error"
                error_type = "stream_error"
                error_message = f"{type(exc).__name__}: {exc}"
                self._logger.warning("stream_error id=%s %s", request_id, error_message)
            except (asyncio.CancelledError, GeneratorExit):
                # The client went away mid-stream. Failures inside the
                # cancellation must not skip the bookkeeping below.
                status = "interrupted"
                error_type = "client_disconnect"
                error_message = "Client disconnected before the stream completed"
                raise
            finally:
                # A client disconnect cancels this task while Starlette tears
                # the response down, which would otherwise abort the database
                # writes below and leave the request stuck on "pending".
                with anyio.CancelScope(shield=True):
                    await self._finalize_stream(
                        response=response,
                        candidate=candidate,
                        account=account,
                        request_id=request_id,
                        attempt_id=attempt_id,
                        attempt_n=attempt_n,
                        started=started,
                        first_byte_at=first_byte_at,
                        key_id=key_id,
                        price_in=price_in,
                        price_out=price_out,
                        price_cache_in=price_cache_in,
                        price_cache_write=price_cache_write,
                        record_usage=record_usage,
                        accumulator=accumulator,
                        status=status,
                        error_type=error_type,
                        error_message=error_message,
                    )

        headers = filter_response_headers(response.headers, streaming=True)
        headers.pop("content-type", None)
        headers.pop("Content-Type", None)
        return StreamingResponse(
            iterator(),
            status_code=response.status_code,
            headers=headers,
            media_type="text/event-stream",
        )

    async def _finalize_stream(
        self,
        *,
        response: httpx.Response,
        candidate: Candidate,
        account: dict[str, Any],
        request_id: str,
        attempt_id: int,
        attempt_n: int,
        started: float,
        first_byte_at: float | None,
        key_id: int | None,
        price_in: float,
        price_out: float,
        price_cache_in: float | None,
        price_cache_write: float | None,
        record_usage: bool,
        accumulator: _SseAccumulator,
        status: str,
        error_type: str | None,
        error_message: str | None,
    ) -> None:
        """Persist a finished stream, keeping going if one write fails."""
        if accumulator.stream_error and status == "success":
            status = "error"
            error_type = "stream_error"
            error_message = accumulator.stream_error
        usage = accumulator.usage
        cost = estimate_cost(
            price_in=price_in,
            price_out=price_out,
            price_cache_in=price_cache_in,
            price_cache_write=price_cache_write,
            usage=usage,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        ttft_ms = int((first_byte_at - started) * 1000) if first_byte_at else None
        await response.aclose()
        try:
            await self._repo.add_payload(
                request_id=request_id,
                attempt_n=attempt_n,
                kind="response",
                body=_dump(
                    {
                        "streamed": True,
                        "text": accumulator.text,
                        "finish_reason": accumulator.finish_reason,
                        "usage": {
                            "input_tokens": usage.input_tokens,
                            "output_tokens": usage.output_tokens,
                            "cache_read_tokens": usage.cache_read_tokens,
                            "cache_write_tokens": usage.cache_write_tokens,
                        },
                    }
                ),
            )
        except Exception:
            self._logger.exception("stream_payload_failed id=%s", request_id)
        try:
            await self._repo.finish_attempt(
                attempt_id,
                {
                    "status": status,
                    "http_status": response.status_code,
                    "error_type": error_type,
                    "error_message": error_message,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_write_tokens": usage.cache_write_tokens,
                    "cost": cost,
                },
            )
        except Exception:
            self._logger.exception("stream_attempt_failed id=%s", request_id)
        if record_usage and (
            status == "success" or (status == "interrupted" and usage.total_tokens)
        ):
            try:
                await self._record_usage(
                    request_id=request_id,
                    candidate=candidate,
                    account=account,
                    key_id=key_id,
                    usage=usage,
                    cost=cost,
                )
            except Exception:
                self._logger.exception("stream_usage_failed id=%s", request_id)
        try:
            await self._repo.finish_request(
                request_id,
                {
                    "resolved_provider": candidate.provider_name,
                    "resolved_model": candidate.model,
                    "status": status,
                    "http_status": response.status_code,
                    "error_type": error_type,
                    "error_message": error_message,
                    "duration_ms": duration_ms,
                    "ttft_ms": ttft_ms,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_write_tokens": usage.cache_write_tokens,
                    "cost": cost,
                    "attempts": attempt_n,
                },
            )
        except Exception:
            self._logger.exception("stream_request_failed id=%s", request_id)
        self._logger.info(
            "request_stream id=%s provider=%s model=%s status=%s "
            "tokens=%s/%s cache_read=%s ms=%s",
            request_id,
            candidate.provider_name,
            candidate.model,
            status,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            duration_ms,
        )

    # ----------------------------------------------------------------- helpers
    def _pin_account(
        self,
        accounts: list[dict[str, Any]],
        provider_id: int,
        affinity_key: str | None,
    ) -> list[dict[str, Any]]:
        if not affinity_key or not accounts:
            return accounts
        entry = self._affinity.get(affinity_key)
        if entry is None:
            return accounts
        expires, pinned_provider, pinned_account = entry
        if time.monotonic() >= expires:
            self._affinity.pop(affinity_key, None)
            return accounts
        if pinned_provider != provider_id:
            return accounts
        for index, account in enumerate(accounts):
            if account["id"] != pinned_account:
                continue
            if index == 0:
                return accounts
            return [account, *accounts[:index], *accounts[index + 1 :]]
        return accounts

    def _remember_affinity(
        self,
        affinity_key: str,
        provider_id: int,
        account_id: int,
        ttl_seconds: int,
    ) -> None:
        self._affinity[affinity_key] = (
            time.monotonic() + ttl_seconds,
            provider_id,
            account_id,
        )
        if len(self._affinity) <= 4096:
            return
        now = time.monotonic()
        for key, (expires, _, _) in list(self._affinity.items()):
            if expires <= now:
                self._affinity.pop(key, None)

    async def _token_saver_enabled(self) -> bool:
        stored = await self._repo.get_setting("token_saver")
        if stored is None:
            return self._settings.token_saver
        return stored == "true"

    async def _record_usage(
        self,
        *,
        request_id: str,
        candidate: Candidate,
        account: dict[str, Any],
        key_id: int | None,
        usage: Usage,
        cost: float,
    ) -> None:
        await self._repo.record_account_use(
            account["id"], usage.input_tokens, usage.output_tokens, usage.cache_read_tokens
        )
        await self._repo.add_usage(
            request_id=request_id,
            provider_id=candidate.provider_id,
            account_id=account["id"],
            key_id=key_id,
            model=candidate.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost=cost,
        )

    async def _finalize_interrupted(
        self,
        request_id: str,
        attempt_id: int | None,
        started: float,
        attempts: int,
    ) -> None:
        """Record a request cancelled before its response started streaming."""
        duration_ms = int((time.perf_counter() - started) * 1000)
        message = "Client disconnected before the request completed"
        with anyio.CancelScope(shield=True):
            if attempt_id is not None:
                try:
                    await self._repo.finish_attempt(
                        attempt_id,
                        {
                            "status": "interrupted",
                            "error_type": "client_disconnect",
                            "error_message": message,
                        },
                    )
                except Exception:
                    self._logger.exception(
                        "interrupted_attempt_failed id=%s", request_id
                    )
            try:
                await self._repo.finish_request(
                    request_id,
                    {
                        "status": "interrupted",
                        "error_type": "client_disconnect",
                        "error_message": message,
                        "duration_ms": duration_ms,
                        "attempts": attempts,
                    },
                )
            except Exception:
                self._logger.exception("interrupted_request_failed id=%s", request_id)
        self._logger.warning("request_interrupted id=%s", request_id)

    async def _finalize_error(
        self,
        request_id: str,
        exc: GatewayError,
        started: float,
        attempts: int,
    ) -> None:
        duration_ms = int((time.perf_counter() - started) * 1000)
        await self._repo.finish_request(
            request_id,
            {
                "status": "error",
                "http_status": exc.status_code,
                "error_type": exc.type,
                "error_message": exc.message,
                "duration_ms": duration_ms,
                "attempts": attempts,
            },
        )
        self._logger.warning(
            "request_error id=%s status=%s error=%s", request_id, exc.status_code, exc.message
        )
