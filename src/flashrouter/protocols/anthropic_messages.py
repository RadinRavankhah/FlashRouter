"""Anthropic Messages adapter with openai-compatible translation (v0.8)."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from flashrouter.errors import invalid_request


class AnthropicMessagesAdapter:
    """Translates Anthropic /v1/messages to upstream OpenAI-compatible format."""

    name = "anthropic-messages"

    def validate_request(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise invalid_request("Request body must be JSON object")
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise invalid_request("'messages' required array", param="messages")
        for m in messages:
            if not isinstance(m, dict):
                raise invalid_request("Each message must be object")
            if "role" not in m:
                raise invalid_request("Message missing 'role'", param="messages")
        stream = payload.get("stream")
        if stream is not None and not isinstance(stream, bool):
            raise invalid_request("'stream' must be boolean", param="stream")
        return payload

    def is_stream(self, payload: Mapping[str, Any]) -> bool:
        return payload.get("stream") is True

    def prepare_body(self, payload: Mapping[str, Any], upstream_model: str) -> dict[str, Any]:
        body = copy.deepcopy(dict(payload))
        body["model"] = upstream_model
        # Translation: Anthropic messages -> OpenAI messages for custom upstream
        translated = []
        for m in body.get("messages", []):
            msg = dict(m)
            role = msg.get("role")
            # Anthropic tool_use -> assistant with tool_calls
            if role == "assistant" and "tool_use" in msg:
                msg["tool_calls"] = msg.pop("tool_use", [])
                # Normalize tool_use objects to OpenAI format
                tc = []
                for t in msg.get("tool_calls", []):
                    if isinstance(t, dict):
                        tc.append({
                            "id": t.get("id", "call_anon"),
                            "type": "function",
                            "function": {
                                "name": t.get("name", ""),
                                "arguments": str(t.get("input", t.get("arguments", "{}"))),
                            },
                        })
                msg["tool_calls"] = tc
            # Anthropic tool_result -> tool message
            if role == "user" and isinstance(msg.get("content"), list):
                # If content contains tool_result blocks, translate to tool messages
                pass  # kept simple for v0.8 initial
            translated.append(msg)
        body["messages"] = translated
        # Preserve max_tokens where present; don't inject if missing
        return body

    def chat_path(self) -> str:
        return "messages"

    def models_path(self) -> str:
        return "models"
