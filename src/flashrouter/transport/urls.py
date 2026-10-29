"""Upstream URL construction."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def join_url(base_url: str, endpoint: str) -> str:
    """Join an OpenAI API root with an endpoint path.

    ``base_url`` is the provider's API root (for example
    ``https://openrouter.ai/api/v1``). If it has no path component, ``/v1`` is
    inserted so that ``https://api.openai.com`` resolves to
    ``https://api.openai.com/v1/chat/completions``.
    """

    parts = urlsplit(base_url)
    base_path = parts.path.rstrip("/")
    endpoint_path = endpoint.strip("/")

    if not base_path:
        base_path = "/v1"

    path = f"{base_path}/{endpoint_path}"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
