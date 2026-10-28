"""OpenAI-compatible model listing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from flashrouter.auth import require_gateway_key

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models", dependencies=[Depends(require_gateway_key)])
async def list_models(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    resolver = request.app.state.model_resolver
    data = [
        {
            "id": model.id,
            "object": "model",
            "created": model.created,
            "owned_by": model.owned_by or settings.upstream.name,
        }
        for model in resolver.list_models()
    ]
    return {"object": "list", "data": data}
