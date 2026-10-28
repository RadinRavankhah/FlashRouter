"""Inference endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from starlette.responses import Response

from flashrouter.errors import invalid_request
from flashrouter.storage.repository import RequestRepository

router = APIRouter(prefix="/v1", tags=["inference"])


def _get_repository(request: Request) -> RequestRepository:
    repo = request.app.state.request_repository
    if repo is None:
        raise invalid_request(
            "Request history storage is not available", code="storage_unavailable"
        )
    return repo


@router.post("/chat/completions")
async def chat_completions(request: Request) -> Response:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise invalid_request("Request body must be valid JSON") from exc

    repo = _get_repository(request)
    request_id = request.state.request_id
    model_id = payload.get("model") if isinstance(payload, dict) else None
    wants_stream = isinstance(payload, dict) and payload.get("stream") is True

    # Persist the initial request record and incoming body before any upstream
    # dispatch. If persistence fails, reject the request without calling upstream
    # (no unlogged spend).
    try:
        await repo.create_request(
            request_id=request_id,
            gateway_key_id="default",
            client_ip=request.client.host if request.client else None,
            method=request.method,
            path=request.url.path,
            protocol="openai-chat",
            mode="stream" if wants_stream else "complete",
            model_id=model_id or "",
            upstream_model=None,
        )
        await repo.add_payload(
            request_id=request_id,
            kind="request_incoming",
            body_bytes=raw_body,
        )
    except Exception as exc:
        from flashrouter.errors import GatewayError

        raise GatewayError(
            status_code=500,
            message="Request history storage failed",
            code="storage_unavailable",
        ) from exc

    proxy = request.app.state.proxy
    if wants_stream:
        return await proxy.stream(payload, request_id, model_id=model_id)
    return await proxy.complete(payload, request_id, model_id=model_id)
