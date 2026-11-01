"""Usage normalization and cost estimation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Usage:
    """Normalized token usage from an OpenAI-compatible response.

    ``input_tokens`` is the total prompt size, including cache reads/writes.
    Cache fields are subsets of it, so ``uncached_input_tokens`` is what is
    billed at the regular input price.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def uncached_input_tokens(self) -> int:
        return max(self.input_tokens - self.cache_read_tokens - self.cache_write_tokens, 0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _as_int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _first_int(*values: Any) -> int:
    for value in values:
        if value is not None:
            return _as_int(value)
    return 0


def _details(usage: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _usage_payload(payload: Any) -> dict[str, Any] | None:
    """Return the usage object from OpenAI/Responses/Anthropic payloads.

    Anthropic streaming ``message_start`` events nest usage under
    ``message.usage``; everything else puts it at the top level.
    """
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if isinstance(usage, dict):
        return usage
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("usage"), dict):
        return message["usage"]
    return None


def extract_usage(payload: Any) -> Usage:
    """Return normalized token usage from an OpenAI- or Anthropic-style payload."""
    usage = _usage_payload(payload)
    if usage is None:
        return Usage()

    prompt_details = _details(usage, "prompt_tokens_details", "input_tokens_details")
    cache_read = _first_int(
        prompt_details.get("cached_tokens"),
        usage.get("cache_read_input_tokens"),
        usage.get("cache_read_tokens"),
        usage.get("cached_tokens"),
        usage.get("prompt_cache_hit_tokens"),
    )
    cache_write = _first_int(
        usage.get("cache_creation_input_tokens"),
        usage.get("cache_write_tokens"),
        usage.get("cache_creation_tokens"),
    )

    input_tokens = _first_int(usage.get("prompt_tokens"), usage.get("input_tokens"))
    # Anthropic-style payloads report uncached input separately from cache tokens.
    separate_cache = (
        "prompt_tokens" not in usage
        and ("cache_read_input_tokens" in usage or "cache_creation_input_tokens" in usage)
    )
    if separate_cache:
        input_tokens += cache_read + cache_write

    return Usage(
        input_tokens=input_tokens,
        output_tokens=_first_int(usage.get("completion_tokens"), usage.get("output_tokens")),
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )


def estimate_cost(
    *,
    price_in: float,
    price_out: float,
    price_cache_in: float | None = None,
    price_cache_write: float | None = None,
    usage: Usage,
) -> float:
    """Estimated USD cost using price per 1M tokens (0 means unknown).

    Cache reads are billed at ``price_cache_in`` (falling back to ``price_in``
    when not configured). Cache writes use ``price_cache_write`` when set,
    otherwise twice ``price_in``.
    """
    cache_price = price_in if price_cache_in is None else price_cache_in
    write_price = price_in * 2.0 if price_cache_write is None else price_cache_write
    cost = (
        usage.uncached_input_tokens * price_in
        + usage.cache_read_tokens * cache_price
        + usage.cache_write_tokens * write_price
        + usage.output_tokens * price_out
    )
    return round(cost / 1_000_000.0, 8)


def usage_from_sse_line(line: str) -> Usage | None:
    """Parse a single SSE ``data:`` line and return usage if present."""
    line = line.strip()
    if not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if not data or data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except (ValueError, TypeError):
        return None
    if _usage_payload(payload) is None:
        return None
    return extract_usage(payload)


def merge_usage(base: Usage, update: Usage) -> Usage:
    """Merge incrementally reported usage.

    Anthropic streams usage in two events (``message_start`` carries the input
    and cache counts, ``message_delta`` the final output count), so fields are
    combined with ``max`` rather than replaced.
    """
    return Usage(
        input_tokens=max(base.input_tokens, update.input_tokens),
        output_tokens=max(base.output_tokens, update.output_tokens),
        cache_read_tokens=max(base.cache_read_tokens, update.cache_read_tokens),
        cache_write_tokens=max(base.cache_write_tokens, update.cache_write_tokens),
    )
