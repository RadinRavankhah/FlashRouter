"""Prompt-cache policy and marker injection.

Anthropic-compatible providers cache a prompt only when it carries
``cache_control`` breakpoints; DeepSeek, OpenAI and Gemini cache automatically.
FlashRouter therefore writes breakpoints only for targets that are known to
accept them, and strips them everywhere else so requests stay valid.

The anchoring policy follows Anthropic's documented layout (``tools`` ->
``system`` -> ``messages``) with at most four breakpoints per request:

* last system block, 1h TTL when requested;
* last cacheable tool, 1h TTL when requested;
* last assistant block (or the final message on the first turn);
* a tool loop's final ``tool_result`` turn, when a slot is free.

Requests that already carry markers are respected: they are sanitized and
capped at four instead of being rewritten.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from typing import Any

OFF = "off"
AUTO = "auto"
FORCE = "force"
MODES = {OFF, AUTO, FORCE}

PROVIDER_MARKERS = {"auto", "anthropic", "none"}
MAX_BREAKPOINTS = 4

TTL_5M = "5m"
TTL_1H = "1h"

_ANTHROPIC_ENDPOINTS = {"messages"}
_OPENAI_MARKER_ENDPOINTS = {"chat/completions"}
_PROMPT_KEY_ENDPOINTS = {"chat/completions", "responses"}
_CACHEABLE_ENDPOINTS = {"messages", *_PROMPT_KEY_ENDPOINTS}
_THINKING_BLOCKS = {"thinking", "redacted_thinking"}

AFFINITY_TTL_SECONDS = 15 * 60
AFFINITY_TTL_1H_SECONDS = 60 * 60


@dataclass(frozen=True)
class CacheDecision:
    mode: str
    active: bool
    inject: bool
    strip: bool
    send_cache_key: bool
    head_ttl: str
    tail_ttl: str

    @property
    def affinity_ttl(self) -> int:
        if self.inject and self.head_ttl == TTL_1H:
            return AFFINITY_TTL_1H_SECONDS
        return AFFINITY_TTL_SECONDS


def normalize_ttl(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return TTL_1H if raw in {"1h", "60m", "hour"} else TTL_5M


def resolve_cache_decision(
    *,
    endpoint: str,
    provider: dict[str, Any] | None,
    key: dict[str, Any] | None,
    model: dict[str, Any] | None = None,
    override: str | None = None,
) -> CacheDecision:
    """Resolve the cache behavior for one attempt.

    For non-``off`` model policies the priority is request header override ->
    model ``force`` -> API key policy -> provider capability. A model policy of
    ``off`` is a hard off: it ignores every other layer so no cache hints or
    headers reach the provider.

    ``auto`` is cache-optimized for every target: explicit markers for
    Anthropic-capable providers, and routing hints/affinity for providers that
    cache automatically. ``off`` strips markers and disables all optimizations.
    """
    if endpoint not in _CACHEABLE_ENDPOINTS:
        return CacheDecision(OFF, False, False, False, False, TTL_5M, TTL_5M)

    model_policy = str((model or {}).get("cache_policy") or AUTO).strip().lower()
    if model_policy not in MODES:
        model_policy = AUTO

    markers = str((provider or {}).get("cache_markers") or AUTO).strip().lower()
    if markers not in PROVIDER_MARKERS:
        markers = AUTO
    ttl = normalize_ttl(
        (model or {}).get("cache_ttl")
        or (key or {}).get("cache_ttl")
        or (provider or {}).get("cache_ttl")
    )
    protocol = str((provider or {}).get("protocol") or "")
    anthropic = protocol == "anthropic-messages"
    prompt_key = endpoint in _PROMPT_KEY_ENDPOINTS

    if model_policy == OFF:
        return CacheDecision(OFF, False, False, True, False, ttl, TTL_5M)

    policy = str(override or "").strip().lower()
    if policy not in MODES:
        if model_policy == FORCE:
            policy = FORCE
        else:
            policy = str((key or {}).get("cache_policy") or AUTO).strip().lower()
    if policy not in MODES:
        policy = AUTO

    if policy == OFF:
        return CacheDecision(OFF, False, False, True, False, ttl, TTL_5M)

    if policy == FORCE:
        return CacheDecision(
            FORCE, True, True, False, prompt_key and not anthropic, ttl, TTL_5M
        )

    inject = markers == "anthropic" or (markers != "none" and anthropic)
    return CacheDecision(
        AUTO,
        True,
        inject,
        not inject,
        prompt_key and not anthropic and markers != "none",
        ttl,
        TTL_5M,
    )


def prompt_cache_key(affinity_key: str | None) -> str | None:
    """Return a stable, opaque ``prompt_cache_key`` for a conversation."""
    if not affinity_key:
        return None
    digest = hashlib.sha256(affinity_key.encode("utf-8")).hexdigest()[:40]
    return f"fr_{digest}"


def apply_prompt_cache_key(
    body: dict[str, Any],
    *,
    affinity_key: str | None,
    decision: CacheDecision,
) -> dict[str, Any]:
    """Attach a stable prompt-cache routing hint when caching is enabled."""
    if not decision.send_cache_key or body.get("prompt_cache_key"):
        return body
    cache_key = prompt_cache_key(affinity_key)
    if not cache_key:
        return body
    result = dict(body)
    result["prompt_cache_key"] = cache_key
    return result


def apply_cache_markers(
    body: dict[str, Any], *, endpoint: str, decision: CacheDecision
) -> dict[str, Any]:
    """Return the body to send upstream, with markers applied or removed."""
    if decision.strip:
        return strip_cache_markers(body)
    if not decision.inject:
        return body
    if endpoint in _ANTHROPIC_ENDPOINTS:
        return anchor_anthropic(body, decision)
    if endpoint in _OPENAI_MARKER_ENDPOINTS:
        return anchor_openai(body, decision)
    return body


def _cache_control(ttl: str) -> dict[str, str]:
    if ttl == TTL_1H:
        return {"type": "ephemeral", "ttl": TTL_1H}
    return {"type": "ephemeral"}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _message_blocks(message: Any) -> list[dict[str, Any]]:
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    if isinstance(content, dict):
        return [content]
    return []


def body_has_markers(body: dict[str, Any]) -> bool:
    if isinstance(body.get("cache_control"), dict):
        return True
    for block in _as_list(body.get("system")):
        if isinstance(block, dict) and block.get("cache_control"):
            return True
    for tool in _as_list(body.get("tools")):
        if isinstance(tool, dict) and tool.get("cache_control"):
            return True
    for message in _as_list(body.get("messages")):
        for block in _message_blocks(message):
            if block.get("cache_control"):
                return True
    for block in _as_list(body.get("input")):
        if isinstance(block, dict):
            if block.get("cache_control"):
                return True
            content = block.get("content")
            if isinstance(content, dict) and content.get("cache_control"):
                return True
            for part in _as_list(content):
                if isinstance(part, dict) and part.get("cache_control"):
                    return True
    return False


def _strip_tool(tool: dict[str, Any]) -> None:
    tool.pop("cache_control", None)
    function = tool.get("function")
    if isinstance(function, dict):
        function.pop("cache_control", None)


def strip_cache_markers(body: dict[str, Any]) -> dict[str, Any]:
    """Remove every cache hint (markers and ``prompt_cache_key``) from a body."""
    if not body_has_markers(body) and "prompt_cache_key" not in body:
        return body
    result = copy.deepcopy(body)
    result.pop("cache_control", None)
    result.pop("prompt_cache_key", None)
    for block in _as_list(result.get("system")):
        if isinstance(block, dict):
            block.pop("cache_control", None)
    for tool in _as_list(result.get("tools")):
        if isinstance(tool, dict):
            _strip_tool(tool)
    for message in _as_list(result.get("messages")):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, dict):
            content.pop("cache_control", None)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block.pop("cache_control", None)
    for block in _as_list(result.get("input")):
        if isinstance(block, dict):
            block.pop("cache_control", None)
            content = block.get("content")
            if isinstance(content, dict):
                content.pop("cache_control", None)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        part.pop("cache_control", None)
    return result


def cache_marker_count(body: dict[str, Any]) -> int:
    count = 1 if isinstance(body.get("cache_control"), dict) else 0
    for block in _as_list(body.get("system")):
        if isinstance(block, dict) and block.get("cache_control"):
            count += 1
    for tool in _as_list(body.get("tools")):
        if isinstance(tool, dict) and tool.get("cache_control"):
            count += 1
    for message in _as_list(body.get("messages")):
        for block in _message_blocks(message):
            if block.get("cache_control"):
                count += 1
    return count


# ---------------------------------------------------------------- Anthropic
def _valid_anthropic_block(block: Any) -> bool:
    if not isinstance(block, dict):
        return False
    if block.get("type") in _THINKING_BLOCKS:
        return False
    if block.get("type") == "text":
        return bool(str(block.get("text") or "").strip())
    return True


def _last_cacheable_tool_index(tools: list[Any]) -> int:
    for index in range(len(tools) - 1, -1, -1):
        tool = tools[index]
        if isinstance(tool, dict) and tool.get("defer_loading") is not True:
            return index
    return -1


def _mark_block(block: dict[str, Any], ttl: str) -> None:
    block["cache_control"] = _cache_control(ttl)


def _mark_last_block(blocks: list[Any], ttl: str) -> bool:
    for block in reversed(blocks):
        if _valid_anthropic_block(block):
            _mark_block(block, ttl)
            return True
    return False


def _mark_last_assistant(messages: list[Any], ttl: str) -> bool:
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            if not content.strip():
                return False
            message["content"] = [
                {"type": "text", "text": content, "cache_control": _cache_control(ttl)}
            ]
            return True
        return _mark_last_block(_as_list(content), ttl)
    return False


def _mark_final_tool_results(messages: list[Any], ttl: str) -> bool:
    if not messages:
        return False
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "user":
        return False
    blocks = _as_list(last.get("content"))
    if not any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in blocks
    ):
        return False
    if any(isinstance(block, dict) and block.get("cache_control") for block in blocks):
        return False
    return _mark_last_block(blocks, ttl)


def _sanitize_anthropic(body: dict[str, Any]) -> None:
    for tool in _as_list(body.get("tools")):
        if isinstance(tool, dict) and tool.get("defer_loading") is True:
            tool.pop("cache_control", None)
    for message in _as_list(body.get("messages")):
        for block in _message_blocks(message):
            if block.get("type") in _THINKING_BLOCKS:
                block.pop("cache_control", None)
            elif block.get("type") == "text" and not str(block.get("text") or "").strip():
                block.pop("cache_control", None)


def _cap_anthropic(body: dict[str, Any]) -> None:
    """Trim markers past the four-breakpoint budget, keeping the head anchors."""
    system = _as_list(body.get("system"))
    tools = _as_list(body.get("tools"))
    messages = _as_list(body.get("messages"))

    head: set[int] = set()
    if system and isinstance(system[-1], dict):
        head.add(id(system[-1]))
    tool_index = _last_cacheable_tool_index(tools)
    if tool_index >= 0 and isinstance(tools[tool_index], dict):
        head.add(id(tools[tool_index]))

    marked: list[dict[str, Any]] = []
    for block in system:
        if isinstance(block, dict) and block.get("cache_control"):
            marked.append(block)
    for tool in tools:
        if isinstance(tool, dict) and tool.get("cache_control"):
            marked.append(tool)
    for message in messages:
        for block in _message_blocks(message):
            if block.get("cache_control"):
                marked.append(block)

    total = len(marked) + (1 if isinstance(body.get("cache_control"), dict) else 0)
    rest = [block for block in marked if id(block) not in head]
    keep = max(0, MAX_BREAKPOINTS - (total - len(rest)))
    for block in rest[: max(0, len(rest) - keep)]:
        block.pop("cache_control", None)


def anchor_anthropic(
    body: dict[str, Any], decision: CacheDecision
) -> dict[str, Any]:
    result = copy.deepcopy(body)
    _sanitize_anthropic(result)
    if body_has_markers(result):
        _cap_anthropic(result)
        return result

    system = result.get("system")
    if isinstance(system, str):
        if system.strip():
            result["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": _cache_control(decision.head_ttl),
                }
            ]
    elif isinstance(system, list) and system:
        _mark_last_block(system, decision.head_ttl)

    tools = _as_list(result.get("tools"))
    if tools:
        tool_index = _last_cacheable_tool_index(tools)
        if tool_index >= 0:
            _mark_block(tools[tool_index], decision.head_ttl)

    messages = _as_list(result.get("messages"))
    if messages:
        if not _mark_last_assistant(messages, decision.tail_ttl):
            last = messages[-1]
            if isinstance(last, dict):
                content = last.get("content")
                if isinstance(content, str):
                    if content.strip():
                        last["content"] = [
                            {
                                "type": "text",
                                "text": content,
                                "cache_control": _cache_control(decision.tail_ttl),
                            }
                        ]
                else:
                    _mark_last_block(_as_list(content), decision.tail_ttl)
        if cache_marker_count(result) < MAX_BREAKPOINTS:
            _mark_final_tool_results(messages, decision.tail_ttl)

    return result


# ------------------------------------------------------------------ OpenAI
def _openai_block_text(block: dict[str, Any]) -> bool:
    kind = block.get("type")
    if kind in {"text", "input_text"}:
        return bool(str(block.get("text") or "").strip())
    return False


def _mark_openai_content(message: dict[str, Any], ttl: str) -> bool:
    content = message.get("content")
    if isinstance(content, str):
        if not content.strip():
            return False
        message["content"] = [
            {"type": "text", "text": content, "cache_control": _cache_control(ttl)}
        ]
        return True
    if isinstance(content, dict):
        if _openai_block_text(content):
            content["cache_control"] = _cache_control(ttl)
            return True
        return False
    if isinstance(content, list):
        for block in reversed(content):
            if isinstance(block, dict) and _openai_block_text(block):
                block["cache_control"] = _cache_control(ttl)
                return True
    return False


def anchor_openai(body: dict[str, Any], decision: CacheDecision) -> dict[str, Any]:
    result = copy.deepcopy(body)
    if body_has_markers(result):
        return result

    messages = _as_list(result.get("messages"))
    if not messages:
        return result

    for message in messages:
        if isinstance(message, dict) and message.get("role") in {"system", "developer"}:
            _mark_openai_content(message, decision.head_ttl)
            break

    for message in reversed(messages):
        if (
            isinstance(message, dict)
            and message.get("role") == "assistant"
            and _mark_openai_content(message, decision.tail_ttl)
        ):
            break

    return result
