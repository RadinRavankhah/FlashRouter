"""Admin API: setup, request history, stats, health, and key management."""

from __future__ import annotations

import json as _json
import secrets as _secrets
import time
from typing import Any

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from flashrouter.admin.models import LoginRequest  # noqa: F401  (kept for import compat)
from flashrouter.config import (
    AdminConfig,
    GatewayConfig,
    ModelConfig,
    ServerConfig,
    Settings,
    UpstreamConfig,
    is_configured,
    save_config,
)
from flashrouter.errors import authentication_error, invalid_request
from flashrouter.transport.urls import join_upstream_url

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


# -- setup ----------------------------------------------------------------

@router.get("/setup/status")
async def setup_status(request: Request) -> JSONResponse:
    settings = _get_settings(request)
    return JSONResponse({"configured": is_configured(settings)})


@router.post("/setup")
async def setup_save(request: Request, body: dict[str, Any]) -> JSONResponse:
    settings = _get_settings(request)
    if is_configured(settings):
        raise authentication_error("Already configured; setup is not available")

    gateway_key = body.get("gateway_api_key") or _secrets.token_urlsafe(32)
    upstream_base_url = body.get("upstream_base_url", "").strip().rstrip("/")
    upstream_api_key = body.get("upstream_api_key") or None
    upstream_name = body.get("upstream_name", "upstream")
    models_input = body.get("models", [])

    from urllib.parse import urlsplit

    parts = urlsplit(upstream_base_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise invalid_request("upstream_base_url must be an absolute http(s) URL")

    config_path = settings.config_path
    data_dir = settings.data_dir

    new_settings = Settings(
        server=ServerConfig(
            host=settings.server.host,
            port=settings.server.port,
            log_level=settings.server.log_level,
        ),
        gateway=GatewayConfig(api_key=gateway_key),
        upstream=UpstreamConfig(
            name=upstream_name,
            base_url=upstream_base_url,
            protocol="openai-chat",
            api_key=upstream_api_key,
        ),
        admin=AdminConfig(),
        models=[
            ModelConfig(
                id=m.get("id", "model"),
                upstream_model=m.get("upstream_model") or m.get("id", "model"),
                owned_by=m.get("owned_by"),
            )
            for m in models_input
        ]
        or [ModelConfig(id="default", upstream_model="default")],
        config_path=config_path,
        data_dir=data_dir,
    )

    save_config(new_settings)

    # Seed the database with the initial provider, credential, model, and alias.
    repo = _get_repository(request)
    provider_id = _secrets.token_hex(8)
    credential_id = _secrets.token_hex(8)
    model_id = _secrets.token_hex(8)
    alias_id = _secrets.token_hex(8)

    await repo.create_provider(
        provider_id=provider_id,
        name=upstream_name,
        base_url=upstream_base_url,
        protocol="openai-chat",
        enabled=True,
    )
    await repo.create_provider_credential(
        credential_id=credential_id,
        provider_id=provider_id,
        name="primary",
        secret=upstream_api_key or "",
        enabled=True,
    )
    first_model = (
        models_input[0]
        if models_input
        else {"id": "default", "upstream_model": "default"}
    )
    await repo.create_db_model(
        model_id=model_id,
        provider_id=provider_id,
        credential_id=credential_id,
        upstream_model=first_model.get("upstream_model") or first_model.get("id", "default"),
        enabled=True,
    )
    await repo.create_model_alias(
        alias_id=alias_id,
        alias=first_model.get("id", "default"),
        db_model_id=model_id,
        enabled=True,
    )

    # Seed the first gateway key from the configured gateway API key so that
    # client authentication works immediately after setup.
    if gateway_key:
        await repo.create_gateway_key(
            key_id=_secrets.token_hex(8),
            name="default",
            secret=gateway_key,
            enabled=True,
        )

    return JSONResponse({"ok": True, "message": "Configuration saved"})


# -- providers ------------------------------------------------------------

@router.get("/v1/providers")
async def list_providers(request: Request) -> JSONResponse:
    repo = _get_repository(request)
    rows = await repo.list_providers()
    return JSONResponse({"providers": rows})


@router.post("/v1/providers")
async def create_provider(request: Request, body: dict[str, Any]) -> JSONResponse:
    repo = _get_repository(request)
    provider_id = body.get("id") or _secrets.token_hex(8)
    await repo.create_provider(
        provider_id=provider_id,
        name=body.get("name", "Provider"),
        base_url=body.get("base_url", ""),
        protocol=body.get("protocol", "openai-chat"),
        headers=_json.dumps(body.get("headers") or {}),
        connect_timeout_seconds=float(body.get("connect_timeout_seconds", 10)),
        read_timeout_seconds=float(body.get("read_timeout_seconds", 180)),
        verify_tls=bool(body.get("verify_tls", True)),
        trust_env=bool(body.get("trust_env", False)),
        follow_redirects=bool(body.get("follow_redirects", False)),
        enabled=bool(body.get("enabled", True)),
    )
    return JSONResponse({"id": provider_id, "ok": True})


@router.get("/v1/providers/{provider_id}")
async def get_provider(request: Request, provider_id: str) -> JSONResponse:
    repo = _get_repository(request)
    row = await repo.get_provider(provider_id)
    if row is None:
        raise invalid_request("Provider not found", code="not_found")
    return JSONResponse(row)


@router.put("/v1/providers/{provider_id}")
async def update_provider(
    request: Request, provider_id: str, body: dict[str, Any]
) -> JSONResponse:
    repo = _get_repository(request)
    update_kwargs: dict[str, Any] = {}
    for field in (
        "name",
        "base_url",
        "protocol",
        "headers",
        "connect_timeout_seconds",
        "read_timeout_seconds",
        "verify_tls",
        "trust_env",
        "follow_redirects",
        "enabled",
    ):
        if field in body:
            value = body[field]
            if field == "headers" and isinstance(value, dict):
                value = _json.dumps(value)
            if field in ("verify_tls", "trust_env", "follow_redirects", "enabled"):
                value = 1 if value else 0
            update_kwargs[field] = value
    await repo.update_provider(provider_id, **update_kwargs)
    return JSONResponse({"ok": True})


@router.delete("/v1/providers/{provider_id}")
async def delete_provider(request: Request, provider_id: str) -> JSONResponse:
    repo = _get_repository(request)
    await repo.delete_provider(provider_id)
    return JSONResponse({"ok": True})


@router.post("/v1/providers/{provider_id}/test")
async def test_provider(request: Request, provider_id: str, body: dict[str, Any]) -> JSONResponse:
    """Send a minimal (potentially billable) chat request through the provider.

    Validates that the stored credential can reach the upstream. Returns the
    upstream status, duration, and a sanitized response summary.
    """
    repo = _get_repository(request)
    provider = await repo.get_provider(provider_id)
    if provider is None:
        raise invalid_request("Provider not found", code="not_found")

    credential_id = body.get("credential_id")
    credential = None
    if credential_id:
        credential = await repo.get_provider_credential(credential_id)
        if credential is None or credential.get("provider_id") != provider_id:
            raise invalid_request(
                "Credential not found for this provider", code="not_found"
            )
    else:
        credentials = await repo.list_provider_credentials()
        candidates = [
            c
            for c in credentials
            if c.get("provider_id") == provider_id and c.get("enabled")
        ]
        if not candidates:
            raise invalid_request(
                "No enabled credentials for this provider", code="no_credential"
            )
        credential = candidates[0]

    try:
        headers = _json.loads(provider.get("headers") or "{}")
    except Exception:
        headers = {}

    model = body.get("model") or "test"
    messages = body.get("messages") or [
        {"role": "user", "content": "test"}
    ]
    test_body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": body.get("max_tokens", 1),
    }

    request_headers = {
        "Content-Type": "application/json",
        **headers,
    }
    api_key = credential.get("secret") or None
    if api_key:
        request_headers["Authorization"] = f"Bearer {api_key}"

    try:
        content = _json.dumps(test_body).encode("utf-8")
    except Exception as exc:  # pragma: no cover - defensive
        raise invalid_request("Invalid test request body") from exc

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=float(provider.get("connect_timeout_seconds") or 10.0),
                read=float(provider.get("read_timeout_seconds") or 180.0),
                write=float(provider.get("read_timeout_seconds") or 180.0),
                pool=float(provider.get("read_timeout_seconds") or 180.0),
            ),
            verify=bool(provider.get("verify_tls", 1)),
            trust_env=bool(provider.get("trust_env", 0)),
            follow_redirects=bool(provider.get("follow_redirects", 0)),
        ) as client:
            response = await client.post(
                join_upstream_url(provider["base_url"], "/chat/completions"),
                headers=request_headers,
                content=content,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            try:
                response_body = response.json()
            except Exception:
                response_body = {"raw": response.text[:500]}
            return JSONResponse(
                {
                    "ok": response.is_success,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "credential_id": credential["id"],
                    "credential_name": credential.get("name"),
                    "model": model,
                    "body": response_body,
                    "error": None
                    if response.is_success
                    else response_body.get("error", {}).get("message")
                    or response.text[:200],
                }
            )
    except httpx.TimeoutException:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return JSONResponse(
            {
                "ok": False,
                "status": 504,
                "duration_ms": duration_ms,
                "credential_id": credential["id"],
                "credential_name": credential.get("name"),
                "model": model,
                "body": None,
                "error": "upstream_timeout",
            },
            status_code=504,
        )
    except httpx.ConnectError as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return JSONResponse(
            {
                "ok": False,
                "status": 502,
                "duration_ms": duration_ms,
                "credential_id": credential["id"],
                "credential_name": credential.get("name"),
                "model": model,
                "body": None,
                "error": f"connection_failed: {exc}",
            },
            status_code=502,
        )
    except httpx.HTTPError as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return JSONResponse(
            {
                "ok": False,
                "status": 502,
                "duration_ms": duration_ms,
                "credential_id": credential["id"],
                "credential_name": credential.get("name"),
                "model": model,
                "body": None,
                "error": f"request_failed: {exc}",
            },
            status_code=502,
        )


# -- provider credentials -------------------------------------------------

@router.get("/v1/credentials")
async def list_credentials(request: Request) -> JSONResponse:
    repo = _get_repository(request)
    rows = await repo.list_provider_credentials()
    # Mask secrets in list view
    for r in rows:
        secret = r.get("secret")
        if secret:
            if len(secret) <= 8:
                r["secret"] = "*" * len(secret)
            else:
                r["secret"] = f"{secret[:4]}...{secret[-4:]}"
    return JSONResponse({"credentials": rows})


@router.post("/v1/credentials")
async def create_credential(request: Request, body: dict[str, Any]) -> JSONResponse:
    repo = _get_repository(request)
    credential_id = body.get("id") or _secrets.token_hex(8)
    await repo.create_provider_credential(
        credential_id=credential_id,
        provider_id=body.get("provider_id", ""),
        name=body.get("name", "Credential"),
        secret=body.get("secret", ""),
        enabled=bool(body.get("enabled", True)),
    )
    return JSONResponse({"id": credential_id, "ok": True})


@router.get("/v1/credentials/{credential_id}")
async def get_credential(request: Request, credential_id: str) -> JSONResponse:
    repo = _get_repository(request)
    row = await repo.get_provider_credential(credential_id)
    if row is None:
        raise invalid_request("Credential not found", code="not_found")
    return JSONResponse(row)


@router.put("/v1/credentials/{credential_id}")
async def update_credential(
    request: Request, credential_id: str, body: dict[str, Any]
) -> JSONResponse:
    repo = _get_repository(request)
    update_kwargs: dict[str, Any] = {}
    for field in ("provider_id", "name", "secret", "enabled"):
        if field in body:
            update_kwargs[field] = body[field]
    if "enabled" in update_kwargs:
        update_kwargs["enabled"] = 1 if update_kwargs["enabled"] else 0
    await repo.update_provider_credential(credential_id, **update_kwargs)
    return JSONResponse({"ok": True})


@router.delete("/v1/credentials/{credential_id}")
async def delete_credential(request: Request, credential_id: str) -> JSONResponse:
    repo = _get_repository(request)
    await repo.delete_provider_credential(credential_id)
    return JSONResponse({"ok": True})


# -- gateway keys ---------------------------------------------------------

@router.get("/v1/keys")
async def list_keys(request: Request) -> JSONResponse:
    repo = _get_repository(request)
    rows = await repo.list_gateway_keys()
    for r in rows:
        secret = r.get("secret")
        if secret:
            if len(secret) <= 8:
                r["secret"] = "*" * len(secret)
            else:
                r["secret"] = f"{secret[:4]}...{secret[-4:]}"
    return JSONResponse({"keys": rows})


@router.post("/v1/keys")
async def create_key(request: Request, body: dict[str, Any]) -> JSONResponse:
    repo = _get_repository(request)
    key_id = body.get("id") or _secrets.token_hex(8)
    await repo.create_gateway_key(
        key_id=key_id,
        name=body.get("name", "Key"),
        secret=body.get("secret", ""),
        enabled=bool(body.get("enabled", True)),
    )
    return JSONResponse({"id": key_id, "ok": True})


@router.get("/v1/keys/{key_id}")
async def get_key(request: Request, key_id: str) -> JSONResponse:
    repo = _get_repository(request)
    row = await repo.get_gateway_key(key_id)
    if row is None:
        raise invalid_request("Key not found", code="not_found")
    return JSONResponse(row)


@router.put("/v1/keys/{key_id}")
async def update_key(request: Request, key_id: str, body: dict[str, Any]) -> JSONResponse:
    repo = _get_repository(request)
    update_kwargs: dict[str, Any] = {}
    for field in ("name", "secret", "enabled"):
        if field in body:
            update_kwargs[field] = body[field]
    if "enabled" in update_kwargs:
        update_kwargs["enabled"] = 1 if update_kwargs["enabled"] else 0
    await repo.update_gateway_key(key_id, **update_kwargs)
    return JSONResponse({"ok": True})


@router.delete("/v1/keys/{key_id}")
async def delete_key(request: Request, key_id: str) -> JSONResponse:
    repo = _get_repository(request)
    await repo.delete_gateway_key(key_id)
    return JSONResponse({"ok": True})


# -- models ---------------------------------------------------------------

@router.get("/v1/dbmodels")
async def list_models(request: Request) -> JSONResponse:
    repo = _get_repository(request)
    rows = await repo.list_db_models()
    return JSONResponse({"models": rows})


@router.post("/v1/dbmodels")
async def create_model(request: Request, body: dict[str, Any]) -> JSONResponse:
    repo = _get_repository(request)
    model_id = body.get("id") or _secrets.token_hex(8)
    await repo.create_db_model(
        model_id=model_id,
        provider_id=body.get("provider_id", ""),
        credential_id=body.get("credential_id"),
        upstream_model=body.get("upstream_model", ""),
        enabled=bool(body.get("enabled", True)),
    )
    return JSONResponse({"id": model_id, "ok": True})


@router.get("/v1/dbmodels/{model_id}")
async def get_model(request: Request, model_id: str) -> JSONResponse:
    repo = _get_repository(request)
    row = await repo.get_db_model(model_id)
    if row is None:
        raise invalid_request("Model not found", code="not_found")
    return JSONResponse(row)


@router.put("/v1/dbmodels/{model_id}")
async def update_model(request: Request, model_id: str, body: dict[str, Any]) -> JSONResponse:
    repo = _get_repository(request)
    update_kwargs: dict[str, Any] = {}
    for field in ("provider_id", "credential_id", "upstream_model", "enabled"):
        if field in body:
            update_kwargs[field] = body[field]
    if "enabled" in update_kwargs:
        update_kwargs["enabled"] = 1 if update_kwargs["enabled"] else 0
    await repo.update_db_model(model_id, **update_kwargs)
    return JSONResponse({"ok": True})


@router.delete("/v1/dbmodels/{model_id}")
async def delete_model(request: Request, model_id: str) -> JSONResponse:
    repo = _get_repository(request)
    await repo.delete_db_model(model_id)
    return JSONResponse({"ok": True})


# -- model aliases --------------------------------------------------------

@router.get("/v1/aliases")
async def list_aliases(request: Request) -> JSONResponse:
    repo = _get_repository(request)
    rows = await repo.list_model_aliases()
    return JSONResponse({"aliases": rows})


@router.post("/v1/aliases")
async def create_alias(request: Request, body: dict[str, Any]) -> JSONResponse:
    repo = _get_repository(request)
    alias_id = body.get("id") or _secrets.token_hex(8)
    await repo.create_model_alias(
        alias_id=alias_id,
        alias=body.get("alias", ""),
        db_model_id=body.get("db_model_id", ""),
        enabled=bool(body.get("enabled", True)),
    )
    return JSONResponse({"id": alias_id, "ok": True})


@router.get("/v1/aliases/{alias_id}")
async def get_alias(request: Request, alias_id: str) -> JSONResponse:
    repo = _get_repository(request)
    row = await repo.get_model_alias(alias_id)
    if row is None:
        raise invalid_request("Alias not found", code="not_found")
    return JSONResponse(row)


@router.put("/v1/aliases/{alias_id}")
async def update_alias(request: Request, alias_id: str, body: dict[str, Any]) -> JSONResponse:
    repo = _get_repository(request)
    update_kwargs: dict[str, Any] = {}
    for field in ("alias", "db_model_id", "enabled"):
        if field in body:
            update_kwargs[field] = body[field]
    if "enabled" in update_kwargs:
        update_kwargs["enabled"] = 1 if update_kwargs["enabled"] else 0
    await repo.update_model_alias(alias_id, **update_kwargs)
    return JSONResponse({"ok": True})


@router.delete("/v1/aliases/{alias_id}")
async def delete_alias(request: Request, alias_id: str) -> JSONResponse:
    repo = _get_repository(request)
    await repo.delete_model_alias(alias_id)
    return JSONResponse({"ok": True})


# -- requests / stats / health --------------------------------------------

@router.get("/v1/requests")
async def list_requests(
    request: Request,
    model: str | None = Query(default=None),
    status: int | None = Query(default=None),
    gateway_key: str | None = Query(default=None),
    credential: str | None = Query(default=None),
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
        gateway_key=gateway_key,
        credential=credential,
        date_from=date_from,
        date_to=date_to,
        request_id=request_id,
    )
    return JSONResponse({"requests": rows, "limit": limit, "offset": offset})


@router.get("/v1/requests/{request_id}")
async def get_request(
    request_id: str,
    request: Request,
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
async def stats(request: Request) -> JSONResponse:
    repo = _get_repository(request)
    data = await repo.get_stats()
    return JSONResponse(data)


@router.get("/v1/health")
async def health(request: Request) -> JSONResponse:
    repo = _get_repository(request)
    health_data = await repo.storage_health()
    return JSONResponse(health_data)
