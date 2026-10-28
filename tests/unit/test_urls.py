from __future__ import annotations

import pytest

from flashrouter.transport.urls import join_upstream_url


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        (
            "https://openrouter.ai/api/v1",
            "https://openrouter.ai/api/v1/chat/completions",
        ),
        (
            "https://openrouter.ai/api/v1/",
            "https://openrouter.ai/api/v1/chat/completions",
        ),
        (
            "http://127.0.0.1:1234/v1",
            "http://127.0.0.1:1234/v1/chat/completions",
        ),
        (
            "https://example.test",
            "https://example.test/v1/chat/completions",
        ),
        (
            "https://example.test/api",
            "https://example.test/api/v1/chat/completions",
        ),
    ],
)
def test_join_upstream_url(base_url: str, expected: str) -> None:
    assert join_upstream_url(base_url, "chat/completions") == expected


def test_join_upstream_url_accepts_leading_slash_endpoint() -> None:
    result = join_upstream_url("https://example.test/v1", "/models")
    assert result == "https://example.test/v1/models"


def test_models_endpoint() -> None:
    assert join_upstream_url("https://example.test/v1/", "models") == (
        "https://example.test/v1/models"
    )
