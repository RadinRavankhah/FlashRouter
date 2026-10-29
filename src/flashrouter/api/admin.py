"""Dashboard admin API."""

from __future__ import annotations

import shutil
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from flashrouter import __version__
from flashrouter.errors import bad_request
from flashrouter.providers.presets import PRESETS, get_preset
from flashrouter.transport.headers import build_upstream_headers
from flashrouter.transport.urls import join_url

router = APIRouter(prefix="/admin/api")


# --------------------------------------------------------------------- schemas
class ProviderIn(BaseModel):
    name: str
    base_url: str = ""
    preset: str = "custom"
    protocol: str = "openai-chat"
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    priority: int = 100


class AccountIn(BaseModel):
    name: str
    secret: str = ""
    weight: int = 1
    priority: int = 100
    enabled: bool = True
    cooldown_seconds: int = 60


class TargetIn(BaseModel):
    provider_id: int
    model: str
    enabled: bool = True


class ComboIn(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    targets: list[TargetIn] = Field(default_factory=list)


class KeyIn(BaseModel):
    name: str
    allowed_combos: list[str] = Field(default_factory=list)
    enabled: bool = True


class ModelIn(BaseModel):
    provider_id: int
    model: str
    display_name: str | None = None
    price_in: float = 0
    price_out: float = 0
    price_cache_in: float | None = None


class ModelPriceIn(BaseModel):
    price_in: float = 0
    price_out: float = 0
    price_cache_in: float | None = None


class SettingsIn(BaseModel):
    token_saver: bool | None = None


# --------------------------------------------------------------------- helpers
def _repo(request: Request):
    return request.app.state.repository


def _mask(value: str | None, keep: int = 6) -> str:
    if not value:
        return ""
    if len(value) <= keep + 4:
        return value[:2] + "..." if len(value) > 2 else "..."
    return f"{value[:keep]}...{value[-4:]}"


def _provider_out(provider: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": provider["id"],
        "name": provider["name"],
        "preset": provider["preset"],
        "base_url": provider["base_url"],
        "protocol": provider["protocol"],
        "headers": provider.get("headers", {}),
        "enabled": provider["enabled"],
        "priority": provider["priority"],
        "account_count": provider.get("account_count", 0),
        "model_count": provider.get("model_count", 0),
        "created_at": provider.get("created_at"),
        "updated_at": provider.get("updated_at"),
    }


def _account_out(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": account["id"],
        "provider_id": account["provider_id"],
        "name": account["name"],
        "secret_masked": _mask(account.get("secret")),
        "has_secret": bool(account.get("secret")),
        "weight": account["weight"],
        "priority": account["priority"],
        "enabled": account["enabled"],
        "cooling_until": account.get("cooling_until"),
        "last_error": account.get("last_error"),
        "cooldown_seconds": account.get("cooldown_seconds", 60),
        "requests": account.get("requests", 0),
        "input_tokens": account.get("input_tokens", 0),
        "output_tokens": account.get("output_tokens", 0),
        "cache_read_tokens": account.get("cache_read_tokens", 0),
    }


def _key_out(key: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": key["id"],
        "name": key["name"],
        "token_masked": _mask(key["token"], keep=10),
        "enabled": key["enabled"],
        "allowed_combos": key.get("allowed_combos", []),
        "last_used_at": key.get("last_used_at"),
        "created_at": key.get("created_at"),
    }


def _normalize_base_url(base_url: str) -> str:
    base_url = (base_url or "").strip()
    if not base_url:
        return ""
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise bad_request("base_url must be an absolute http(s) URL", param="base_url")
    return base_url.rstrip("/")


async def _probe_models(request: Request, provider: dict[str, Any], secret: str | None):
    client = request.app.state.http_client
    url = join_url(provider["base_url"], "models")
    headers = build_upstream_headers(provider.get("headers"), secret, stream=False)
    headers["Accept"] = "application/json"
    try:
        response = await client.get(url, headers=headers)
    except Exception as exc:  # noqa: BLE001 - report any transport failure
        return {"ok": False, "url": url, "status": 0, "error": str(exc), "models": []}
    models: list[str] = []
    if response.status_code < 400:
        try:
            payload = response.json()
            for item in payload.get("data", []):
                if isinstance(item, dict) and item.get("id"):
                    models.append(str(item["id"]))
        except Exception:  # noqa: BLE001
            models = []
    return {
        "ok": response.status_code < 400,
        "url": url,
        "status": response.status_code,
        "error": None if response.status_code < 400 else response.text[:500],
        "models": models,
    }


# ---------------------------------------------------------------------- status
@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    repo = _repo(request)
    settings = request.app.state.settings
    db_path = settings.database_path
    db_size = db_path.stat().st_size if db_path.exists() else 0
    try:
        free = shutil.disk_usage(settings.data_dir).free
    except OSError:
        free = 0
    return {
        "version": __version__,
        "database": str(db_path),
        "database_bytes": db_size,
        "free_bytes": free,
        "counts": {
            "providers": len(await repo.list_providers()),
            "accounts": len(await repo.list_accounts()),
            "combos": len(await repo.list_combos()),
            "keys": await repo.count_keys(),
        },
    }


# -------------------------------------------------------------------- presets
@router.get("/providers/presets")
async def list_presets() -> list[dict[str, Any]]:
    return PRESETS


# ------------------------------------------------------------------ providers
@router.get("/providers")
async def list_providers(request: Request) -> list[dict[str, Any]]:
    return [_provider_out(p) for p in await _repo(request).list_providers()]


@router.post("/providers")
async def create_provider(request: Request, payload: ProviderIn) -> dict[str, Any]:
    repo = _repo(request)
    base_url = payload.base_url
    preset = payload.preset
    if preset != "custom":
        preset_data = get_preset(preset)
        if preset_data is None:
            raise bad_request(f"Unknown provider preset '{preset}'", param="preset")
        if not base_url:
            base_url = preset_data["base_url"]
    base_url = _normalize_base_url(base_url)
    if not base_url:
        raise bad_request("base_url is required", param="base_url")
    provider_id = await repo.create_provider(
        name=payload.name.strip() or "Provider",
        base_url=base_url,
        preset=preset,
        protocol=payload.protocol,
        headers=payload.headers,
        enabled=payload.enabled,
        priority=payload.priority,
    )
    provider = await repo.get_provider(provider_id)
    assert provider is not None
    return _provider_out(provider)


@router.put("/providers/{provider_id}")
async def update_provider(
    request: Request, provider_id: int, payload: ProviderIn
) -> dict[str, Any]:
    repo = _repo(request)
    if await repo.get_provider(provider_id) is None:
        raise bad_request("Provider not found", param="provider_id")
    base_url = _normalize_base_url(payload.base_url) if payload.base_url else None
    fields: dict[str, Any] = {
        "name": payload.name,
        "preset": payload.preset,
        "protocol": payload.protocol,
        "headers": payload.headers,
        "enabled": payload.enabled,
        "priority": payload.priority,
    }
    if base_url:
        fields["base_url"] = base_url
    await repo.update_provider(provider_id, fields)
    provider = await repo.get_provider(provider_id)
    assert provider is not None
    return _provider_out(provider)


@router.delete("/providers/{provider_id}")
async def delete_provider(request: Request, provider_id: int) -> dict[str, Any]:
    await _repo(request).delete_provider(provider_id)
    return {"deleted": provider_id}


@router.post("/providers/{provider_id}/test")
async def test_provider(request: Request, provider_id: int) -> dict[str, Any]:
    repo = _repo(request)
    provider = await repo.get_provider(provider_id)
    if provider is None:
        raise bad_request("Provider not found", param="provider_id")
    accounts = await repo.list_accounts(provider_id)
    secret = accounts[0]["secret"] if accounts else None
    return await _probe_models(request, provider, secret)


@router.post("/providers/{provider_id}/discover")
async def discover_models(request: Request, provider_id: int) -> dict[str, Any]:
    repo = _repo(request)
    provider = await repo.get_provider(provider_id)
    if provider is None:
        raise bad_request("Provider not found", param="provider_id")
    accounts = await repo.list_accounts(provider_id)
    secret = accounts[0]["secret"] if accounts else None
    probe = await _probe_models(request, provider, secret)
    if not probe["ok"]:
        return probe
    for model in probe["models"]:
        await repo.ensure_model(provider_id=provider_id, model=model)
    probe["imported"] = len(probe["models"])
    return probe


# ------------------------------------------------------------------- accounts
@router.get("/providers/{provider_id}/accounts")
async def list_accounts(request: Request, provider_id: int) -> list[dict[str, Any]]:
    return [_account_out(a) for a in await _repo(request).list_accounts(provider_id)]


@router.post("/providers/{provider_id}/accounts")
async def create_account(
    request: Request, provider_id: int, payload: AccountIn
) -> dict[str, Any]:
    repo = _repo(request)
    if await repo.get_provider(provider_id) is None:
        raise bad_request("Provider not found", param="provider_id")
    account_id = await repo.create_account(
        provider_id=provider_id,
        name=payload.name.strip() or "Account",
        secret=payload.secret,
        weight=payload.weight,
        priority=payload.priority,
        enabled=payload.enabled,
        cooldown_seconds=payload.cooldown_seconds,
    )
    account = await repo.get_account(account_id)
    assert account is not None
    return _account_out(account)


@router.put("/accounts/{account_id}")
async def update_account(
    request: Request, account_id: int, payload: AccountIn
) -> dict[str, Any]:
    repo = _repo(request)
    if await repo.get_account(account_id) is None:
        raise bad_request("Account not found", param="account_id")
    fields: dict[str, Any] = {
        "name": payload.name,
        "weight": payload.weight,
        "priority": payload.priority,
        "enabled": payload.enabled,
        "cooldown_seconds": payload.cooldown_seconds,
    }
    if payload.secret:
        fields["secret"] = payload.secret
    await repo.update_account(account_id, fields)
    account = await repo.get_account(account_id)
    assert account is not None
    return _account_out(account)


@router.delete("/accounts/{account_id}")
async def delete_account(request: Request, account_id: int) -> dict[str, Any]:
    await _repo(request).delete_account(account_id)
    return {"deleted": account_id}


@router.get("/accounts/{account_id}/reveal")
async def reveal_account(request: Request, account_id: int) -> dict[str, str]:
    account = await _repo(request).get_account(account_id)
    if account is None:
        raise bad_request("Account not found", param="account_id")
    return {"secret": account.get("secret", "")}


@router.post("/accounts/{account_id}/test")
async def test_account(request: Request, account_id: int) -> dict[str, Any]:
    repo = _repo(request)
    account = await repo.get_account(account_id)
    if account is None:
        raise bad_request("Account not found", param="account_id")
    provider = await repo.get_provider(account["provider_id"])
    if provider is None:
        raise bad_request("Provider not found", param="provider_id")
    return await _probe_models(request, provider, account.get("secret"))


# --------------------------------------------------------------------- combos
@router.get("/combos")
async def list_combos(request: Request) -> list[dict[str, Any]]:
    return await _repo(request).list_combos()


@router.post("/combos")
async def create_combo(request: Request, payload: ComboIn) -> dict[str, Any]:
    repo = _repo(request)
    name = payload.name.strip()
    if not name:
        raise bad_request("Combo name is required", param="name")
    if await repo.find_combo(name):
        raise bad_request("A combo with this name already exists", param="name")
    combo_id = await repo.create_combo(
        name=name,
        description=payload.description,
        enabled=payload.enabled,
        targets=[t.model_dump() for t in payload.targets],
    )
    combo = await repo.get_combo(combo_id)
    assert combo is not None
    return combo


@router.put("/combos/{combo_id}")
async def update_combo(request: Request, combo_id: int, payload: ComboIn) -> dict[str, Any]:
    repo = _repo(request)
    if await repo.get_combo(combo_id) is None:
        raise bad_request("Combo not found", param="combo_id")
    await repo.update_combo(
        combo_id,
        name=payload.name.strip() or None,
        description=payload.description,
        enabled=payload.enabled,
        targets=[t.model_dump() for t in payload.targets],
    )
    combo = await repo.get_combo(combo_id)
    assert combo is not None
    return combo


@router.delete("/combos/{combo_id}")
async def delete_combo(request: Request, combo_id: int) -> dict[str, Any]:
    await _repo(request).delete_combo(combo_id)
    return {"deleted": combo_id}


# ----------------------------------------------------------------------- keys
@router.get("/keys")
async def list_keys(request: Request) -> list[dict[str, Any]]:
    return [_key_out(k) for k in await _repo(request).list_keys()]


@router.post("/keys")
async def create_key(request: Request, payload: KeyIn) -> dict[str, Any]:
    repo = _repo(request)
    created = await repo.create_key(
        name=payload.name.strip() or "API key",
        enabled=payload.enabled,
        allowed_combos=payload.allowed_combos,
    )
    return {
        "id": created["id"],
        "name": created["name"],
        "token": created["token"],
    }


@router.put("/keys/{key_id}")
async def update_key(request: Request, key_id: int, payload: KeyIn) -> dict[str, Any]:
    repo = _repo(request)
    if await repo.get_key(key_id) is None:
        raise bad_request("Key not found", param="key_id")
    await repo.update_key(
        key_id,
        {
            "name": payload.name,
            "enabled": payload.enabled,
            "allowed_combos": payload.allowed_combos,
        },
    )
    key = await repo.get_key(key_id)
    assert key is not None
    return _key_out(key)


@router.delete("/keys/{key_id}")
async def delete_key(request: Request, key_id: int) -> dict[str, Any]:
    await _repo(request).delete_key(key_id)
    return {"deleted": key_id}


@router.get("/keys/{key_id}/reveal")
async def reveal_key(request: Request, key_id: int) -> dict[str, str]:
    key = await _repo(request).get_key(key_id)
    if key is None:
        raise bad_request("Key not found", param="key_id")
    return {"token": key["token"]}


# --------------------------------------------------------------------- models
@router.get("/models")
async def list_models(request: Request, provider_id: int | None = None) -> list[dict[str, Any]]:
    return await _repo(request).list_models(provider_id)


@router.post("/models")
async def create_model(request: Request, payload: ModelIn) -> dict[str, Any]:
    repo = _repo(request)
    if await repo.get_provider(payload.provider_id) is None:
        raise bad_request("Provider not found", param="provider_id")
    model_id = await repo.upsert_model(
        provider_id=payload.provider_id,
        model=payload.model.strip(),
        display_name=payload.display_name,
        price_in=payload.price_in,
        price_out=payload.price_out,
        price_cache_in=payload.price_cache_in,
        source="manual",
    )
    return {"id": model_id, "provider_id": payload.provider_id, "model": payload.model}


@router.put("/models/{model_id}")
async def update_model(
    request: Request, model_id: int, payload: ModelPriceIn
) -> dict[str, Any]:
    changed = await _repo(request).update_model_pricing(
        model_id,
        price_in=payload.price_in,
        price_out=payload.price_out,
        price_cache_in=payload.price_cache_in,
    )
    if not changed:
        raise bad_request("Model not found", param="model_id")
    return {"updated": model_id}


@router.delete("/models/{model_id}")
async def delete_model(request: Request, model_id: int) -> dict[str, Any]:
    await _repo(request).delete_model(model_id)
    return {"deleted": model_id}


# ------------------------------------------------------------------- requests
@router.get("/requests")
async def list_requests(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    model: str | None = None,
    key_id: int | None = None,
) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    return await _repo(request).list_requests(
        limit=limit, offset=max(0, offset), status=status, model=model, key_id=key_id
    )


@router.get("/requests/{request_id}")
async def get_request(request: Request, request_id: str) -> dict[str, Any]:
    record = await _repo(request).get_request(request_id)
    if record is None:
        raise bad_request("Request not found", param="request_id")
    return record


# ---------------------------------------------------------------------- stats
@router.get("/stats")
async def stats(request: Request) -> dict[str, Any]:
    return await _repo(request).stats()


# ------------------------------------------------------------------- settings
@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    repo = _repo(request)
    stored = await repo.get_setting("token_saver")
    token_saver = (
        (stored == "true") if stored is not None else request.app.state.settings.token_saver
    )
    return {"token_saver": token_saver}


@router.put("/settings")
async def update_settings(request: Request, payload: SettingsIn) -> dict[str, Any]:
    repo = _repo(request)
    if payload.token_saver is not None:
        await repo.set_setting("token_saver", "true" if payload.token_saver else "false")
    return await get_settings(request)
