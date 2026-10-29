"""OpenAI-compatible inference endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from flashrouter.errors import bad_request, forbidden, unauthorized

router = APIRouter(prefix="/v1")


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key", "").strip()


async def authenticate(request: Request) -> dict[str, Any] | None:
    """Return the key row, or None when the gateway has no keys yet.

    Authentication is only enforced once at least one client key exists, so a
    fresh install can be used immediately after setup.
    """
    repo = request.app.state.repository
    if await repo.count_keys() == 0:
        return None
    token = _bearer(request)
    if not token:
        raise unauthorized()
    key = await repo.get_key_by_token(token)
    if key is None:
        raise unauthorized()
    if not key["enabled"]:
        raise forbidden()
    return key


def _token_saver_override(request: Request) -> bool | None:
    value = request.headers.get("x-flashrouter-token-saver", "").strip().lower()
    if value in {"off", "false", "0", "no", "disabled"}:
        return False
    if value in {"on", "true", "1", "yes", "enabled"}:
        return True
    return None


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise bad_request("Request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object")
    return body


@router.post("/chat/completions")
async def chat_completions(request: Request):
    key = await authenticate(request)
    body = await _json_body(request)
    if key is not None:
        await request.app.state.repository.touch_key(key["id"])
    engine = request.app.state.engine
    return await engine.handle(
        body=body,
        key=key,
        request_id=request.state.request_id,
        endpoint="chat/completions",
        stream=bool(body.get("stream")),
        token_saver=_token_saver_override(request),
    )


@router.post("/responses")
async def responses(request: Request):
    key = await authenticate(request)
    body = await _json_body(request)
    if key is not None:
        await request.app.state.repository.touch_key(key["id"])
    engine = request.app.state.engine
    return await engine.handle(
        body=body,
        key=key,
        request_id=request.state.request_id,
        endpoint="responses",
        stream=bool(body.get("stream")),
    )


@router.get("/models")
async def list_models(request: Request):
    await authenticate(request)
    repo = request.app.state.repository
    data: list[dict[str, Any]] = []
    seen: set[str] = set()

    for combo in await repo.list_combos():
        if not combo["enabled"]:
            continue
        seen.add(combo["name"])
        data.append(
            {
                "id": combo["name"],
                "object": "model",
                "created": 0,
                "owned_by": "flashrouter",
            }
        )

    for model in await repo.list_models():
        if not model["enabled"]:
            continue
        model_id = f"{model['provider_name']}/{model['model']}"
        if model_id in seen:
            continue
        seen.add(model_id)
        data.append(
            {
                "id": model_id,
                "object": "model",
                "created": 0,
                "owned_by": model["provider_name"],
            }
        )

    return JSONResponse({"object": "list", "data": data})
