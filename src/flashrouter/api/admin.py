"""Admin API: login, request history, stats, health."""

from __future__ import annotations

import secrets as _secrets

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from flashrouter.admin.models import LoginRequest
from flashrouter.auth.jwt import encode_admin_token, get_admin_secret, require_admin_token
from flashrouter.config import Settings
from flashrouter.errors import authentication_error, invalid_request

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_repository(request: Request):
    repo = request.app.state.request_repository
    if repo is None:
        raise invalid_request(
            "Request history storage is not available", code="storage_unavailable"
        )
    return repo


@router.post("/login")
async def admin_login(
    request: Request,
    login: LoginRequest,
) -> JSONResponse:
    settings = _get_settings(request)
    if not _secrets.compare_digest(login.api_key, settings.gateway_api_key()):
        raise authentication_error("Invalid admin API key")

    token = encode_admin_token(get_admin_secret(settings))
    return JSONResponse({"access_token": token, "token_type": "bearer"})


@router.get("/v1/requests")
async def list_requests(
    request: Request,
    _: None = Depends(require_admin_token),
    model: str | None = Query(default=None),
    status: int | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    repo = _get_repository(request)
    rows = await repo.list_requests(
        limit=limit,
        offset=offset,
        model=model,
        status=status,
        date_from=date_from,
        date_to=date_to,
        request_id=request_id,
    )
    return JSONResponse({"requests": rows, "limit": limit, "offset": offset})


@router.get("/v1/requests/{request_id}")
async def get_request(
    request_id: str,
    request: Request,
    _: None = Depends(require_admin_token),
) -> JSONResponse:
    repo = _get_repository(request)
    req = await repo.get_request(request_id)
    if req is None:
        raise invalid_request("Request not found", code="not_found")
    attempts = await repo.get_attempts(request_id)
    payloads = await repo.get_payloads(request_id)
    for p in payloads:
        raw = p.get("body_bytes")
        if isinstance(raw, str):
            p["body"] = raw
        elif isinstance(raw, bytes):
            p["body"] = raw.decode("utf-8", errors="replace")
        elif raw is not None:
            p["body"] = str(raw)
        p.pop("body_bytes", None)
        p.pop("size_bytes", None)
    return JSONResponse({"request": req, "attempts": attempts, "payloads": payloads})


@router.get("/v1/stats")
async def stats(
    request: Request,
    _: None = Depends(require_admin_token),
) -> JSONResponse:
    repo = _get_repository(request)
    data = await repo.get_stats()
    return JSONResponse(data)


@router.get("/v1/health")
async def health(
    request: Request,
    _: None = Depends(require_admin_token),
) -> JSONResponse:
    repo = _get_repository(request)
    health_data = await repo.storage_health()
    return JSONResponse(health_data)
