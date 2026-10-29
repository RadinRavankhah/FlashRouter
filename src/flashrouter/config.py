"""Configuration loading.

FlashRouter is configured primarily from the dashboard (stored in SQLite). The
TOML file and environment only need to describe where to run and where to store
data. A config file is optional; sensible defaults are used when it is absent.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Raised when a configuration file is present but invalid."""


DEFAULT_PORT = 20128
DEFAULT_HOST = "127.0.0.1"


def default_data_dir() -> Path:
    env = os.environ.get("FLASHROUTER_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "FlashRouter"
        return Path.home() / "AppData" / "Local" / "FlashRouter"
    return Path.home() / ".local" / "share" / "flashrouter"


def resolve_config_path(path: Path | None = None) -> Path:
    if path is not None:
        return path.expanduser()
    env = os.environ.get("FLASHROUTER_CONFIG")
    if env:
        return Path(env).expanduser()
    return default_data_dir() / "config.toml"


@dataclass
class ServerConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    log_level: str = "info"


@dataclass
class AdminConfig:
    token: str | None = None


@dataclass
class Settings:
    server: ServerConfig = field(default_factory=ServerConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)
    data_dir: Path = field(default_factory=default_data_dir)
    config_path: Path = field(default_factory=resolve_config_path)
    token_saver: bool = True
    max_retries: int = 2
    connect_timeout: float = 10.0
    request_timeout: float = 300.0

    @property
    def database_path(self) -> Path:
        return self.data_dir / "flashrouter.db"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"


def _coerce_int(value: object, name: str) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _coerce_float(value: object, name: str) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number") from exc


def _apply_env(settings: Settings) -> None:
    env = os.environ
    if "FLASHROUTER_HOST" in env:
        settings.server.host = env["FLASHROUTER_HOST"]
    if "FLASHROUTER_PORT" in env:
        settings.server.port = _coerce_int(env["FLASHROUTER_PORT"], "FLASHROUTER_PORT")
    if "FLASHROUTER_LOG_LEVEL" in env:
        settings.server.log_level = env["FLASHROUTER_LOG_LEVEL"]
    if "FLASHROUTER_DATA_DIR" in env:
        settings.data_dir = Path(env["FLASHROUTER_DATA_DIR"]).expanduser()
    if "FLASHROUTER_ADMIN_TOKEN" in env:
        settings.admin.token = env["FLASHROUTER_ADMIN_TOKEN"] or None
    if "FLASHROUTER_TOKEN_SAVER" in env:
        settings.token_saver = env["FLASHROUTER_TOKEN_SAVER"].strip().lower() not in {
            "0",
            "false",
            "off",
            "no",
        }


def load_config(path: Path | None = None) -> Settings:
    """Load settings. Missing file is not an error (defaults + dashboard setup)."""
    config_path = resolve_config_path(path)
    settings = Settings(config_path=config_path, data_dir=default_data_dir())

    if config_path.exists():
        try:
            raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"Cannot read {config_path}: {exc}") from exc

        server = raw.get("server", {}) or {}
        if not isinstance(server, dict):
            raise ConfigError("[server] must be a table")
        if "host" in server:
            settings.server.host = str(server["host"])
        if "port" in server:
            settings.server.port = _coerce_int(server["port"], "server.port")
        if "log_level" in server:
            settings.server.log_level = str(server["log_level"])

        admin = raw.get("admin", {}) or {}
        if isinstance(admin, dict) and admin.get("token"):
            settings.admin.token = str(admin["token"])

        gateway = raw.get("gateway", {}) or {}
        if isinstance(gateway, dict):
            if "token_saver" in gateway:
                settings.token_saver = bool(gateway["token_saver"])
            if "max_retries" in gateway:
                settings.max_retries = _coerce_int(gateway["max_retries"], "gateway.max_retries")
            if "connect_timeout" in gateway:
                settings.connect_timeout = _coerce_float(
                    gateway["connect_timeout"], "gateway.connect_timeout"
                )
            if "request_timeout" in gateway:
                settings.request_timeout = _coerce_float(
                    gateway["request_timeout"], "gateway.request_timeout"
                )

        # A config file next to data dir implies the data dir lives beside it.
        if "FLASHROUTER_DATA_DIR" not in os.environ and path is None:
            settings.data_dir = config_path.parent

    _apply_env(settings)
    if not (1 <= settings.server.port <= 65535):
        raise ConfigError("server.port must be between 1 and 65535")
    return settings


def ensure_data_dirs(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
