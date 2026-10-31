from flashrouter.transport.headers import (
    DEFAULT_ANTHROPIC_VERSION,
    build_upstream_headers,
)


def test_openai_headers_use_bearer_only():
    headers = build_upstream_headers({}, "sk-test", stream=False)
    assert headers["Authorization"] == "Bearer sk-test"
    assert "x-api-key" not in headers
    assert "anthropic-version" not in headers


def test_anthropic_headers_send_both_credentials_and_version():
    headers = build_upstream_headers(
        {},
        "sk-ant",
        stream=True,
        dialect="anthropic",
    )
    assert headers["Authorization"] == "Bearer sk-ant"
    assert headers["x-api-key"] == "sk-ant"
    assert headers["anthropic-version"] == DEFAULT_ANTHROPIC_VERSION
    assert headers["Accept"] == "text/event-stream"


def test_anthropic_forwarded_headers_and_provider_override():
    incoming = {
        "anthropic-version": "2024-01-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
        "authorization": "Bearer client-secret",
    }
    headers = build_upstream_headers(
        {"Anthropic-Version": "2023-06-01"},
        "sk-ant",
        stream=False,
        dialect="anthropic",
        incoming=incoming,
    )
    assert headers["Anthropic-Version"] == "2023-06-01"
    assert "anthropic-version" not in headers
    assert headers["anthropic-beta"] == "prompt-caching-2024-07-31"
    assert headers["Authorization"] == "Bearer sk-ant"


def test_client_credentials_are_never_forwarded():
    headers = build_upstream_headers(
        {},
        "sk-ant",
        stream=False,
        dialect="anthropic",
        incoming={"x-api-key": "client-key", "authorization": "Bearer client"},
    )
    assert headers["x-api-key"] == "sk-ant"
    assert headers["Authorization"] == "Bearer sk-ant"


def test_provider_x_api_key_header_is_kept_without_secret():
    headers = build_upstream_headers({"x-api-key": "provider-key"}, None, stream=False)
    assert headers["x-api-key"] == "provider-key"
