"""Header policies for outbound upstream requests and client responses."""

from __future__ import annotations

from collections.abc import Mapping

from flashrouter import __version__

USER_AGENT = f"FlashRouter/{__version__}"

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

# Never forward these from a client to an upstream.
CLIENT_FORBIDDEN_HEADERS = HOP_BY_HOP_HEADERS | {
    "host",
    "content-length",
    "authorization",
    "cookie",
    "origin",
    "referer",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "forwarded",
}

RESPONSE_STRIP_ALWAYS = HOP_BY_HOP_HEADERS | {
    "content-length",
    "set-cookie",
    "set-cookie2",
}


def build_upstream_headers(
    extra_headers: Mapping[str, str] | None,
    secret: str | None,
    *,
    stream: bool,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in (extra_headers or {}).items():
        if name.lower() in CLIENT_FORBIDDEN_HEADERS:
            continue
        headers[name] = value

    headers["Content-Type"] = "application/json"
    headers["Accept"] = "text/event-stream" if stream else "application/json"
    headers["Accept-Encoding"] = "identity"
    headers["User-Agent"] = USER_AGENT

    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    return headers


def filter_response_headers(
    headers: Mapping[str, str],
    *,
    streaming: bool,
) -> dict[str, str]:
    stripped = set(RESPONSE_STRIP_ALWAYS)
    if not streaming:
        # httpx decodes non-streamed bodies, so the original encoding header
        # would no longer describe the bytes returned to the client.
        stripped.add("content-encoding")

    result: dict[str, str] = {}
    for name, value in headers.items():
        if name.lower() in stripped:
            continue
        result[name] = value
    return result
