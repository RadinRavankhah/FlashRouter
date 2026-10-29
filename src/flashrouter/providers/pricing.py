"""Extract per-1M-token prices from OpenAI-compatible model metadata.

OpenAI-compatible APIs are not consistent about pricing. Some providers
(OpenRouter, sometimes Together/Fireworks) include a ``pricing`` object on
each model, while most return only IDs. This module reads the common shapes
and normalizes everything to USD per 1M tokens, which is what the router
stores and bills against.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

_INPUT_KEYS = ("prompt", "input", "input_price", "price_in", "prompt_price")
_OUTPUT_KEYS = ("completion", "output", "output_price", "price_out", "completion_price")
_CACHE_KEYS = (
    "input_cache_read",
    "cache_read",
    "cached_input",
    "cache_read_input",
    "cache_read_price",
    "input_cache_read_price",
)
_OPENROUTER_KEYS = {"prompt", "completion", "input_cache_read"}
_PER_TOKEN_THRESHOLD = 0.001


class ModelPricing(NamedTuple):
    price_in: float | None
    price_out: float | None
    price_cache_in: float | None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _lookup(mapping: dict[str, Any], keys: tuple[str, ...]) -> tuple[str | None, float | None]:
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for key in keys:
        if key in lowered:
            value = _number(lowered[key])
            if value is not None:
                return key, value
    return None, None


def _is_per_token(
    input_key: str | None, output_key: str | None, values: list[float]
) -> bool:
    if any(key in _OPENROUTER_KEYS for key in (input_key, output_key) if key):
        return True
    return bool(values) and max(values) < _PER_TOKEN_THRESHOLD


def _scale(value: float | None, multiplier: int) -> float | None:
    if value is None:
        return None
    return round(value * multiplier, 6)


def extract_model_pricing(item: dict[str, Any]) -> ModelPricing:
    """Return per-1M prices for one model entry, or Nones when unavailable."""
    pricing = item.get("pricing")
    if not isinstance(pricing, dict):
        pricing = item

    input_key, price_in = _lookup(pricing, _INPUT_KEYS)
    output_key, price_out = _lookup(pricing, _OUTPUT_KEYS)
    _, price_cache_in = _lookup(pricing, _CACHE_KEYS)

    if price_in is None and price_out is None:
        return ModelPricing(None, None, None)

    values = [value for value in (price_in, price_out) if value is not None]
    multiplier = 1_000_000 if _is_per_token(input_key, output_key, values) else 1
    return ModelPricing(
        _scale(price_in, multiplier),
        _scale(price_out, multiplier),
        _scale(price_cache_in, multiplier),
    )
