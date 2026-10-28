from __future__ import annotations

from flashrouter.diagnostics import (
    redact_headers,
    redact_proxy_url,
    request_id_headers,
)


def test_redacts_sensitive_headers() -> None:
    headers = {
        "Authorization": "Bearer secret",
        "X-API-Key": "secret",
        "Set-Cookie": "session=secret",
        "Content-Type": "application/json",
    }

    result = redact_headers(headers)

    assert result["Authorization"] == "<redacted>"
    assert result["X-API-Key"] == "<redacted>"
    assert result["Set-Cookie"] == "<redacted>"
    assert result["Content-Type"] == "application/json"


def test_redacts_proxy_credentials() -> None:
    assert redact_proxy_url("http://user:pass@proxy.test:8080") == (
        "http://***:***@proxy.test:8080"
    )
    assert redact_proxy_url("http://proxy.test:8080") == "http://proxy.test:8080"
    assert redact_proxy_url("not a url") == "not a url"


def test_extracts_provider_request_ids() -> None:
    headers = {
        "X-Request-ID": "req_1",
        "X-OpenRouter-Generation-ID": "gen_1",
        "CF-Ray": "ray_1",
        "Content-Type": "application/json",
    }

    result = request_id_headers(headers)

    assert result == {
        "X-Request-ID": "req_1",
        "X-OpenRouter-Generation-ID": "gen_1",
        "CF-Ray": "ray_1",
    }
