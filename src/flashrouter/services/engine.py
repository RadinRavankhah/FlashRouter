"""Request orchestration: routing, fallback, streaming, logging, usage."""

from __future__ import annotations

import json
import time
from typing import Any

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
from flashrouter.services.usage import Usage, estimate_cost, extract_usage, usage_from_sse_line
from flashrouter.storage.repository import Repository
from flashrouter.transport.headers import (
    build_upstream_headers,
    filter_response_headers,
)
from flashrouter.transport.urls import join_url

PAYLOAD_LIMIT = 200_000
STREAM_CAPTURE_LIMIT = 65_536
_READ_CHUNK = 65_536


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


class _SseAccumulator:
    """Best-effort incremental SSE parser for usage and assistant text."""

    def __init__(self) -> None:
        self._buffer = ""
        self.text = ""
        self.usage: Usage = Usage()
        self.finish_reason: str | None = None
        self._truncated = False

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk.decode("utf-8", errors="ignore")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        usage = usage_from_sse_line(line)
        if usage:
            self.usage = usage
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
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                if choice.get("finish_reason"):
                    self.finish_reason = str(choice["finish_reason"])
                delta = choice.get("delta")
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    if not self._truncated:
                        self.text += delta["content"]
                        if len(self.text) >= STREAM_CAPTURE_LIMIT:
                            self._truncated = True


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
    ) -> Response:
        started = time.perf_counter()
        requested_model = str(body.get("model", "") or "")
        key_id = key["id"] if key else None
        key_name = key["name"] if key else None

        await self._repo.create_request(
            request_id=request_id,
            requested_model=requested_model,
            key_id=key_id,
            key_name=key_name,
            stream=stream,
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

        for candidate in candidates:
            eligible = await self._repo.eligible_accounts(candidate.provider_id)
            if not eligible:
                continue
            counter = self._rr.get(candidate.provider_id, 0)
            self._rr[candidate.provider_id] = counter + 1
            accounts = order_accounts(eligible, counter)

            for account in accounts:
                attempts += 1
                attempt_id = await self._repo.add_attempt(
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
                        attempt_id=attempt_id,
                        started=started,
                        key_id=key_id,
                        token_saver=token_saver,
                    )
                except GatewayError as exc:
                    last_error = exc
                    await self._repo.finish_attempt(
                        attempt_id,
                        {
                            "status": "error",
                            "error_type": exc.type,
                            "error_message": exc.message,
                            "http_status": exc.status_code,
                        },
                    )
                    if exc.status_code in (400, 404, 422):
                        await self._finalize_error(request_id, exc, started, attempts)
                        raise
                    continue
                if outcome is not None:
                    return outcome

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
    ) -> Response | None:
        outbound = dict(body)
        outbound["model"] = candidate.model
        saver_enabled = (
            token_saver if token_saver is not None else await self._token_saver_enabled()
        )
        if endpoint == "chat/completions" and saver_enabled:
            outbound = apply_token_saver(outbound)

        await self._repo.add_payload(
            request_id=request_id,
            attempt_n=attempt_n,
            kind="outgoing",
            body=_dump(outbound),
        )

        url = join_url(candidate.base_url, endpoint)
        headers = build_upstream_headers(candidate.headers, account.get("secret"), stream=stream)
        try:
            request = httpx.Request(
                "POST",
                url,
                headers=headers,
                content=json.dumps(outbound, ensure_ascii=False).encode("utf-8"),
            )
        except (TypeError, ValueError) as exc:
            raise upstream_error(502, f"Could not encode request: {exc}") from exc

        price_in, price_out, price_cache_in = await self._repo.get_model_price(
            candidate.provider_id, candidate.model
        )

        if stream:
            response = await self._client.send(request, stream=True)
            if response.status_code >= 400:
                text = (await response.aread()).decode("utf-8", errors="replace")
                await response.aclose()
                await self._handle_http_error(
                    response.status_code, text, candidate, account, attempt_id
                )
                return None
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
            )

        response = await self._client.send(request)
        if response.status_code >= 400:
            text = response.content.decode("utf-8", errors="replace")
            await self._handle_http_error(
                response.status_code, text, candidate, account, attempt_id
            )
            return None

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
    ) -> None:
        retryable, cooldown, error_type = _classify(status)
        message = text[:1000] if text else f"Upstream returned HTTP {status}"
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
    ) -> StreamingResponse:
        async def iterator():
            accumulator = _SseAccumulator()
            first_byte_at: float | None = None
            status = "success"
            error_message: str | None = None
            try:
                async for chunk in response.aiter_raw():
                    if first_byte_at is None:
                        first_byte_at = time.perf_counter()
                    accumulator.feed(chunk)
                    yield chunk
            except httpx.HTTPError as exc:
                status = "error"
                error_message = f"{type(exc).__name__}: {exc}"
                self._logger.warning("stream_error id=%s %s", request_id, error_message)
            finally:
                await response.aclose()
                usage = accumulator.usage
                cost = estimate_cost(
                    price_in=price_in,
                    price_out=price_out,
                    price_cache_in=price_cache_in,
                    usage=usage,
                )
                duration_ms = int((time.perf_counter() - started) * 1000)
                ttft_ms = (
                    int((first_byte_at - started) * 1000) if first_byte_at else None
                )
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
                await self._repo.finish_attempt(
                    attempt_id,
                    {
                        "status": status,
                        "http_status": response.status_code,
                        "error_message": error_message,
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "cache_read_tokens": usage.cache_read_tokens,
                        "cache_write_tokens": usage.cache_write_tokens,
                        "cost": cost,
                    },
                )
                if status == "success":
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
                        "status": status,
                        "http_status": response.status_code,
                        "error_type": "stream_error" if status != "success" else None,
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

        headers = filter_response_headers(response.headers, streaming=True)
        headers.pop("content-type", None)
        headers.pop("Content-Type", None)
        return StreamingResponse(
            iterator(),
            status_code=response.status_code,
            headers=headers,
            media_type="text/event-stream",
        )

    # ----------------------------------------------------------------- helpers
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
