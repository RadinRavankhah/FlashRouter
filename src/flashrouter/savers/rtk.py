"""RTK-style token saver.

Compresses oversized tool outputs (``git diff``, ``grep``, ``ls``, logs, ...)
inside OpenAI chat messages before they are sent upstream. Compression is
best-effort and always fails open: if anything goes wrong the original text is
returned unchanged.
"""

from __future__ import annotations

import copy
import re
from typing import Any

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_MAX_CHARS = 24_000
_MAX_LINES = 480
_KEEP_HEAD_LINES = 160
_KEEP_TAIL_LINES = 120


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _dedup_consecutive(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    previous = None
    count = 0
    for line in lines:
        if line == previous:
            count += 1
            continue
        if count > 0:
            result.append(f"  ... ({count} identical line(s) omitted)")
            count = 0
        result.append(line)
        previous = line
    if count > 0:
        result.append(f"  ... ({count} identical line(s) omitted)")
    return "\n".join(result)


def _smart_truncate(text: str) -> str:
    lines = text.splitlines()
    if len(lines) > _MAX_LINES:
        head = lines[:_KEEP_HEAD_LINES]
        tail = lines[-_KEEP_TAIL_LINES:]
        omitted = len(lines) - len(head) - len(tail)
        text = "\n".join(
            [*head, f"  ... ({omitted} line(s) omitted by FlashRouter RTK) ...", *tail]
        )
    if len(text) > _MAX_CHARS:
        head = text[: _MAX_CHARS // 2]
        tail = text[-(_MAX_CHARS // 2) :]
        omitted = len(text) - len(head) - len(tail)
        text = f"{head}\n  ... ({omitted} char(s) omitted by FlashRouter RTK) ...\n{tail}"
    return text


def compress_text(text: str) -> str:
    if not isinstance(text, str) or len(text) < 600:
        return text
    try:
        compact = _strip_ansi(text)
        compact = _dedup_consecutive(compact)
        compact = _smart_truncate(compact)
        # Never make the payload larger.
        return compact if len(compact) < len(text) else text
    except Exception:  # pragma: no cover - defensive fail-open
        return text


def _compress_message(message: dict[str, Any]) -> bool:
    """Compress a single tool-result message in place. Returns True if changed."""
    if message.get("role") != "tool":
        return False
    changed = False
    content = message.get("content")
    if isinstance(content, str):
        compressed = compress_text(content)
        if compressed != content:
            message["content"] = compressed
            changed = True
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                original = part.get("text", "")
                compressed = compress_text(original)
                if compressed != original:
                    part["text"] = compressed
                    changed = True
    return changed


def apply_token_saver(body: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the request body with tool outputs compressed."""
    try:
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return body
        new_body = copy.deepcopy(body)
        for message in new_body.get("messages", []):
            if isinstance(message, dict):
                _compress_message(message)
        return new_body
    except Exception:  # pragma: no cover - defensive fail-open
        return body
