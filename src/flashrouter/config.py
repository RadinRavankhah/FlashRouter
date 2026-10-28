"""Configuration loading and validation for FlashRouter."""

from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

FORBIDDEN_CUSTOM_HEADERS = {
    "authorization",
    "connection",
    "content-length",
    "cookie",
    "host",
    "keep-alive",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


class ConfigError(Exception):
    """Raised when configuration cannot be located, parsed, or validated."""


def default_data_dir() -> Path:
    override = os.getenv("FLASHROUTER_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "FlashRouter"
        return Path.home() / "AppData" / "Local" / "FlashRouter"

    return Path.home() / ".local" / "share" / "flashrouter"


def resolve_config_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()

    env_path = os.getenv("FLASHROUTER_CONFIG", "").strip()
    if env_path:
        return Path(env_path).expanduser()

    return default_data_dir() / "config.toml"


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = DEFAULT_HOST
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)
    log_level: Literal["debug", "info", "warning", "error"] = "info"


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr | None = None

    @field_validator("api_key")
    @classmethod
    def normalize_empty_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        return value


class UpstreamConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "upstream"
    base_url: str
    protocol: Literal["openai-chat"] = "openai-chat"
    api_key: SecretStr | None = None
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=180.0, gt=0)
    verify_tls: bool = True
    trust_env: bool = False
    follow_redirects: bool = False
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def base_url_must_be_http(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("upstream.base_url must be an absolute http(s) URL")
        if parts.query or parts.fragment:
            raise ValueError("upstream.base_url must not contain a query string or fragment")
        return value

    @field_validator("api_key")
    @classmethod
    def normalize_empty_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        return value

    @field_validator("headers")
    @classmethod
    def validate_custom_headers(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for name, header_value in value.items():
            if not name.strip():
                raise ValueError("upstream.headers contains a blank header name")
            if not isinstance(header_value, str):
                raise ValueError(f"upstream.headers[{name!r}] must be a string")
            if name.lower() in FORBIDDEN_CUSTOM_HEADERS:
                raise ValueError(f"upstream.headers must not contain {name!r}")
            normalized[name] = header_value
        return normalized


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    upstream_model: str | None = None
    owned_by: str | None = None
    created: int = Field(default=0, ge=0)

    @field_validator("id")
    @classmethod
    def id_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("models[].id must not be blank")
        return value

    @field_validator("upstream_model")
    @classmethod
    def upstream_model_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("models[].upstream_model must not be blank")
        return value

    @model_validator(mode="after")
    def default_upstream_model(self) -> ModelConfig:
        if self.upstream_model is None:
            self.upstream_model = self.id
        return self


class AdminConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_key: str = ""
    enabled: bool = True

    @field_validator("secret_key")
    @classmethod
    def _default_secret_key(cls, value: str) -> str:
        if not value.strip():
            import secrets as _secrets

            return _secrets.token_urlsafe(32)
        return value


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerConfig = Field(default_factory=ServerConfig)
    gateway: GatewayConfig
    upstream: UpstreamConfig
    admin: AdminConfig = Field(default_factory=AdminConfig)
    models: list[ModelConfig]
    config_path: Path | None = Field(default=None, exclude=True)
    data_dir: Path = Field(default_factory=default_data_dir, exclude=True)

    @model_validator(mode="after")
    def models_must_be_unique(self) -> Settings:
        if not self.models:
            raise ValueError("at least one [[models]] entry is required")
        ids = [model.id for model in self.models]
        duplicates = sorted({model_id for model_id in ids if ids.count(model_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate model ids: {', '.join(duplicates)}")
        return self

    def gateway_api_key(self) -> str:
        return self.gateway.api_key.get_secret_value()

    def upstream_api_key(self) -> str | None:
        if self.upstream.api_key is None:
            return None
        return self.upstream.api_key.get_secret_value()

    def admin_secret_key(self) -> str:
        return self.admin.secret_key


def _env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip()


def _env_bool(name: str) -> bool | None:
    value = _env(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean (true/false)")


def _env_int(name: str) -> int | None:
    value = _env(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _env_float(name: str) -> float | None:
    value = _env(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(raw)
    server = data.setdefault("server", {})
    gateway = data.setdefault("gateway", {})
    upstream = data.setdefault("upstream", {})
    headers = upstream.setdefault("headers", {})

    if (value := _env("FLASHROUTER_HOST")) is not None:
        server["host"] = value
    if (value_int := _env_int("FLASHROUTER_PORT")) is not None:
        server["port"] = value_int
    if (value := _env("FLASHROUTER_LOG_LEVEL")) is not None:
        server["log_level"] = value.lower()

    if (value := _env("FLASHROUTER_GATEWAY_API_KEY")) is not None:
        gateway["api_key"] = value

    for env_name, field_name in (
        ("FLASHROUTER_UPSTREAM_NAME", "name"),
        ("FLASHROUTER_UPSTREAM_BASE_URL", "base_url"),
        ("FLASHROUTER_UPSTREAM_PROTOCOL", "protocol"),
    ):
        if (value := _env(env_name)) is not None:
            upstream[field_name] = value

    if (value := _env("FLASHROUTER_UPSTREAM_API_KEY")) is not None:
        upstream["api_key"] = value

    if (value_float := _env_float("FLASHROUTER_UPSTREAM_CONNECT_TIMEOUT_SECONDS")) is not None:
        upstream["connect_timeout_seconds"] = value_float
    if (value_float := _env_float("FLASHROUTER_UPSTREAM_READ_TIMEOUT_SECONDS")) is not None:
        upstream["read_timeout_seconds"] = value_float

    for env_name, field_name in (
        ("FLASHROUTER_UPSTREAM_VERIFY_TLS", "verify_tls"),
        ("FLASHROUTER_UPSTREAM_TRUST_ENV", "trust_env"),
        ("FLASHROUTER_UPSTREAM_FOLLOW_REDIRECTS", "follow_redirects"),
    ):
        if (value_bool := _env_bool(env_name)) is not None:
            upstream[field_name] = value_bool

    if (value := _env("FLASHROUTER_UPSTREAM_HTTP_REFERER")) is not None:
        headers["HTTP-Referer"] = value
    if (value := _env("FLASHROUTER_UPSTREAM_TITLE")) is not None:
        headers["X-OpenRouter-Title"] = value

    if not headers:
        upstream.pop("headers", None)
    return data


def load_config(path: Path | str | None = None) -> Settings:
    config_path = resolve_config_path(path)
    data_dir = default_data_dir()

    if not config_path.exists():
        raise ConfigError(
            f"Configuration file not found: {config_path}\n"
            "Copy config.example.toml to that location and fill in the required keys, "
            "or pass --config /path/to/config.toml."
        )

    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {config_path}: {exc}") from exc

    raw = _apply_env_overrides(raw)
    raw["config_path"] = config_path
    raw["data_dir"] = data_dir

    try:
        return Settings.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"Invalid configuration in {config_path}: {exc}") from exc


def ensure_data_dirs(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "logs").mkdir(parents=True, exist_ok=True)


def mask_secret(secret: str | None) -> str:
    if not secret:
        return "<not set>"
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


def is_configured(settings: Settings) -> bool:
    """Return True if a config file exists and has a gateway API key."""
    if not settings.config_path or not settings.config_path.exists():
        return False
    if settings.gateway.api_key is None:
        return False
    return bool(settings.gateway.api_key.get_secret_value().strip())


def save_config(settings: Settings) -> None:
    """Persist Settings to TOML at config_path."""
    config_path = settings.config_path or resolve_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    lines.append("[server]")
    lines.append(f'host = "{settings.server.host}"')
    lines.append(f"port = {settings.server.port}")
    lines.append(f'log_level = "{settings.server.log_level}"')
    lines.append("")

    lines.append("[gateway]")
    if settings.gateway.api_key is not None:
        lines.append(f'api_key = "{settings.gateway.api_key.get_secret_value()}"')
    lines.append("")

    lines.append("[upstream]")
    lines.append(f'name = "{settings.upstream.name}"')
    lines.append(f'base_url = "{settings.upstream.base_url}"')
    lines.append(f'protocol = "{settings.upstream.protocol}"')
    if settings.upstream.api_key is not None:
        lines.append(f'api_key = "{settings.upstream.api_key.get_secret_value()}"')
    lines.append(f"connect_timeout_seconds = {settings.upstream.connect_timeout_seconds}")
    lines.append(f"read_timeout_seconds = {settings.upstream.read_timeout_seconds}")
    lines.append(f"verify_tls = {str(settings.upstream.verify_tls).lower()}")
    lines.append(f"trust_env = {str(settings.upstream.trust_env).lower()}")
    lines.append(f"follow_redirects = {str(settings.upstream.follow_redirects).lower()}")
    if settings.upstream.headers:
        lines.append("[upstream.headers]")
        for k, v in settings.upstream.headers.items():
            lines.append(f'{k} = "{v}"')
    lines.append("")

    lines.append("[admin]")
    lines.append(f'secret_key = "{settings.admin.secret_key}"')
    lines.append(f"enabled = {str(settings.admin.enabled).lower()}")
    lines.append("")

    for m in settings.models:
        lines.append("[[models]]")
        lines.append(f'id = "{m.id}"')
        lines.append(f'upstream_model = "{m.upstream_model}"')
        if m.owned_by is not None:
            lines.append(f'owned_by = "{m.owned_by}"')
        lines.append(f"created = {m.created}")
        lines.append("")

    with config_path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))

