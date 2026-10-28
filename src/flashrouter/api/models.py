"""OpenAI-compatible model listing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from flashrouter.errors import invalid_request

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models")
async def list_models(request: Request) -> dict[str, Any]:
    repo = request.app.state.request_repository
    if repo is None:
        raise invalid_request(
            "Request history storage is not available", code="storage_unavailable"
        )
    aliases = await repo.list_model_aliases()
    data = [
        {
            "id": a["alias"],
            "object": "model",
            "created": 0,
            "owned_by": a.get("provider_name", "unknown"),
        }
        for a in aliases
        if a.get("alias_enabled", 1)
    ]
    return {"object": "list", "data": data}
