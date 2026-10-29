"""OpenAI Responses adapter (v0.7 Codex compatibility)."""
from __future__ import annotations
import copy
from collections.abc import Mapping
from typing import Any
from flashrouter.errors import invalid_request

class ResponsesAdapter:
    name = "responses"
    def validate_request(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise invalid_request("JSON object required")
        if "model" not in payload:
            raise invalid_request("'model' required", param="model")
        return payload
    def is_stream(self, payload: Mapping[str, Any]) -> bool:
        return payload.get("stream") is True
    def prepare_body(self, payload: Mapping[str, Any], upstream_model: str) -> dict[str, Any]:
        body = copy.deepcopy(dict(payload))
        body["model"] = upstream_model
        return body
    def chat_path(self) -> str:
        return "responses"
    def models_path(self) -> str:
        return "models"
