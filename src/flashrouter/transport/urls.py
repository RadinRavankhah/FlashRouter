"""Upstream URL construction."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def join_upstream_url(base_url: str, endpoint: str) -> str:
    """Append an API endpoint without producing a duplicate /v1 segment.

    ``base_url`` is expected to be the API root, for example
    ``https://openrouter.ai/api/v1`` or ``http://127.0.0.1:1234/v1``. If the
    configured path does not end in ``/v1``, one is inserted.
    """

    parts = urlsplit(base_url)
    base_path = parts.path.rstrip("/")
    endpoint_path = endpoint.strip("/")

    if base_path.endswith("/v1"):
        path = f"{base_path}/{endpoint_path}"
    elif base_path:
        path = f"{base_path}/v1/{endpoint_path}"
    else:
        path = f"/v1/{endpoint_path}"

    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
