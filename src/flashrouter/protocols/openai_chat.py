"""OpenAI Chat Completions adapter."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from flashrouter.errors import invalid_request


class OpenAIChatAdapter:
    name = "openai-chat"

    def validate_request(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise invalid_request("Request body must be a JSON object")

        model = payload.get("model")
        if not isinstance(model, str) or not model.strip():
            raise invalid_request(
                "'model' is required and must be a non-empty string",
                param="model",
            )

        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise invalid_request("'messages' is required and must be an array", param="messages")

        stream = payload.get("stream")
        if stream is not None and not isinstance(stream, bool):
            raise invalid_request("'stream' must be a boolean", param="stream")

        return payload

    def is_stream(self, payload: Mapping[str, Any]) -> bool:
        return payload.get("stream") is True

    def prepare_body(
        self,
        payload: Mapping[str, Any],
        upstream_model: str,
    ) -> dict[str, Any]:
        body = copy.deepcopy(dict(payload))
        body["model"] = upstream_model
        return body

    def chat_path(self) -> str:
        return "chat/completions"

    def models_path(self) -> str:
        return "models"
