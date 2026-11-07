"""Header policies for outbound upstream requests and client responses."""

from __future__ import annotations

from collections.abc import Mapping

from flashrouter import __version__

USER_AGENT = f"FlashRouter/{__version__}"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"

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

CACHE_HEADERS = {"cache-control", "pragma"}


def _cache_beta_tokens(value: str) -> str:
    """Drop prompt-caching beta flags while keeping unrelated beta features."""
    tokens = [
        token.strip()
        for token in value.split(",")
        if token.strip() and not token.strip().lower().startswith("prompt-caching")
    ]
    return ", ".join(tokens)


def _outbound_header(
    name: str,
    value: str,
    *,
    allow_cache_headers: bool,
    from_client: bool = False,
) -> str | None:
    lowered = name.lower()
    if lowered in CLIENT_FORBIDDEN_HEADERS:
        return None
    if from_client and lowered == "x-api-key":
        return None
    if lowered.startswith("x-flashrouter-"):
        return None
    if not allow_cache_headers:
        if lowered in CACHE_HEADERS:
            return None
        if lowered == "anthropic-beta":
            return _cache_beta_tokens(value) or None
    return value


def build_upstream_headers(
    extra_headers: Mapping[str, str] | None,
    secret: str | None,
    *,
    stream: bool,
    dialect: str | None = None,
    incoming: Mapping[str, str] | None = None,
    allow_cache_headers: bool = True,
) -> dict[str, str]:
    """Build outbound headers.

    ``dialect="anthropic"`` is used for the mirrored ``/v1/messages`` API. It
    forwards the client's ``anthropic-version``/``anthropic-beta`` headers and
    sends the account secret as both ``x-api-key`` and ``Authorization`` so the
    same provider entry works with native Anthropic (x-api-key) and
    Anthropic-compatible aggregators (Bearer).

    ``allow_cache_headers=False`` removes cache-related HTTP headers so a
    per-model ``off`` policy leaves no cache hints in the upstream request.
    """
    headers: dict[str, str] = {}
    lowered: set[str] = set()
    for name, value in (extra_headers or {}).items():
        if name.lower() in CLIENT_FORBIDDEN_HEADERS:
            continue
        kept = _outbound_header(
            name, value, allow_cache_headers=allow_cache_headers
        )
        if kept is None:
            continue
        headers[name] = kept
        lowered.add(name.lower())

    # Client headers are only forwarded from a small allowlist. Provider
    # configuration wins over anything the client sent.
    for name, value in (incoming or {}).items():
        lowered_name = name.lower()
        if lowered_name in lowered:
            continue
        kept = _outbound_header(
            name,
            value,
            allow_cache_headers=allow_cache_headers,
            from_client=True,
        )
        if kept is None:
            continue
        headers[name] = kept
        lowered.add(lowered_name)

    headers["Content-Type"] = "application/json"
    headers["Accept"] = "text/event-stream" if stream else "application/json"
    headers["Accept-Encoding"] = "identity"
    headers["User-Agent"] = USER_AGENT

    if secret:
        headers["Authorization"] = f"Bearer {secret}"
        if dialect == "anthropic":
            headers["x-api-key"] = secret

    if dialect == "anthropic" and "anthropic-version" not in lowered:
        headers["anthropic-version"] = DEFAULT_ANTHROPIC_VERSION

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
