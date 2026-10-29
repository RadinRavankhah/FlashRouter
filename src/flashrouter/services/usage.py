"""Usage normalization and cost estimation."""

from __future__ import annotations

import json
from typing import Any


def extract_usage(payload: Any) -> tuple[int, int]:
    """Return (input_tokens, output_tokens) from an OpenAI-style response."""
    if not isinstance(payload, dict):
        return (0, 0)
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return (0, 0)
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    try:
        return (int(input_tokens), int(output_tokens))
    except (TypeError, ValueError):
        return (0, 0)


def estimate_cost(
    *, price_in: float, price_out: float, input_tokens: int, output_tokens: int
) -> float:
    """Estimated USD cost using price per 1M tokens (0 means unknown)."""
    return round(
        (input_tokens / 1_000_000.0) * price_in
        + (output_tokens / 1_000_000.0) * price_out,
        8,
    )


def usage_from_sse_line(line: str) -> tuple[int, int] | None:
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
    if isinstance(payload, dict) and payload.get("usage"):
        return extract_usage(payload)
    return None
