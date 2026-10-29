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
