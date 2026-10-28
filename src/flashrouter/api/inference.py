"""Inference endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from flashrouter.auth import require_gateway_key
from flashrouter.errors import invalid_request

router = APIRouter(prefix="/v1", tags=["inference"])


@router.post("/chat/completions", dependencies=[Depends(require_gateway_key)])
async def chat_completions(request: Request) -> Response:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise invalid_request("Request body must be valid JSON") from exc

    proxy = request.app.state.proxy
    request_id = request.state.request_id
    wants_stream = isinstance(payload, dict) and payload.get("stream") is True
    if wants_stream:
        return await proxy.stream(payload, request_id)
    return await proxy.complete(payload, request_id)
