from __future__ import annotations

import pytest
from pydantic import ValidationError

from flashrouter.config import UpstreamConfig
from flashrouter.transport.headers import build_upstream_headers, filter_response_headers


def make_upstream(headers: dict[str, str] | None = None) -> UpstreamConfig:
    return UpstreamConfig(
        base_url="https://upstream.test/v1",
        api_key="upstream-secret",
        headers=headers or {},
    )


def test_builds_clean_upstream_headers() -> None:
    upstream = make_upstream({"HTTP-Referer": "https://example.test", "X-Test": "yes"})

    headers = build_upstream_headers(upstream, "upstream-secret", stream=False)

    assert headers["Authorization"] == "Bearer upstream-secret"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["Accept-Encoding"] == "identity"
    assert headers["User-Agent"] == "FlashRouter/0.1.0"
    assert headers["HTTP-Referer"] == "https://example.test"
    assert headers["X-Test"] == "yes"


def test_streaming_uses_event_stream_accept_header() -> None:
    headers = build_upstream_headers(make_upstream(), None, stream=True)

    assert headers["Accept"] == "text/event-stream"
    assert "Authorization" not in headers


def test_forbidden_custom_headers_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        make_upstream({"Authorization": "custom", "Cookie": "secret"})


def test_core_headers_win_over_safe_custom_headers() -> None:
    upstream = make_upstream({"User-Agent": "custom"})

    headers = build_upstream_headers(upstream, "upstream-secret", stream=False)

    assert headers["Authorization"] == "Bearer upstream-secret"
    assert headers["User-Agent"] == "FlashRouter/0.1.0"


def test_filters_response_headers() -> None:
    headers = {
        "Content-Type": "application/json",
        "Content-Length": "123",
        "Content-Encoding": "gzip",
        "Set-Cookie": "secret=1",
        "Connection": "keep-alive",
        "X-Request-ID": "req_123",
    }

    non_streaming = filter_response_headers(headers, streaming=False)
    streaming = filter_response_headers(headers, streaming=True)

    assert non_streaming == {
        "Content-Type": "application/json",
        "X-Request-ID": "req_123",
    }
    assert streaming == {
        "Content-Type": "application/json",
        "Content-Encoding": "gzip",
        "X-Request-ID": "req_123",
    }
