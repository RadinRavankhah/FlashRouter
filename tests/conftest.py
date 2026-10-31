from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from flashrouter.app import create_app
from flashrouter.config import AdminConfig, ServerConfig, Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        server=ServerConfig(host="127.0.0.1", port=20128),
        admin=AdminConfig(),
        data_dir=tmp_path,
        config_path=tmp_path / "config.toml",
    )


def build_client(
    settings: Settings, handler: Callable[[httpx.Request], httpx.Response]
) -> tuple[TestClient, httpx.AsyncClient]:
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(settings, http_client=upstream)
    return TestClient(app), upstream


def chat_completion(
    model: str = "mock-model", content: str = "hello", cached_tokens: int = 0
) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {"cached_tokens": cached_tokens},
        },
    }


def anthropic_message(
    model: str = "mock-model",
    content: str = "hello",
    input_tokens: int = 10,
    output_tokens: int = 5,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": content}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_write_tokens,
            "cache_read_input_tokens": cache_read_tokens,
        },
    }

