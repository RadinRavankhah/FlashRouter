"""Header policies for outbound upstream requests and client responses."""

from __future__ import annotations

from collections.abc import Mapping

from flashrouter.config import UpstreamConfig

USER_AGENT = "FlashRouter/0.1.0"

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

RESPONSE_STRIP_ALWAYS = HOP_BY_HOP_HEADERS | {
    "content-length",
    "set-cookie",
    "set-cookie2",
}


def build_upstream_headers(
    upstream: UpstreamConfig,
    upstream_api_key: str | None,
    *,
    stream: bool,
) -> dict[str, str]:
    headers: dict[str, str] = {}

    for name, value in upstream.headers.items():
        headers[name] = value

    headers["Content-Type"] = "application/json"
    headers["Accept"] = "text/event-stream" if stream else "application/json"
    headers["Accept-Encoding"] = "identity"
    headers["User-Agent"] = USER_AGENT

    if upstream_api_key:
        headers["Authorization"] = f"Bearer {upstream_api_key}"

    return headers


def filter_response_headers(
    headers: Mapping[str, str],
    *,
    streaming: bool,
) -> dict[str, str]:
    stripped = set(RESPONSE_STRIP_ALWAYS)
    if not streaming:
        # httpx decodes non-streamed response bodies, so the original encoding
        # header would no longer describe the bytes returned to the client.
        stripped.add("content-encoding")

    result: dict[str, str] = {}
    for name, value in headers.items():
        if name.lower() in stripped:
            continue
        result[name] = value
    return result
