from __future__ import annotations

from pathlib import Path

import pytest

from flashrouter.config import ConfigError, load_config

VALID_CONFIG = """
[server]
host = "127.0.0.1"
port = 8787
log_level = "info"

[gateway]
api_key = "gateway-secret"

[upstream]
name = "test-upstream"
base_url = "https://upstream.test/v1/"
api_key = "upstream-secret"
connect_timeout_seconds = 5
read_timeout_seconds = 30

[upstream.headers]
X-Custom = "custom-value"

[[models]]
id = "coding-fast"
upstream_model = "real/model"
owned_by = "test"
"""


def write_config(tmp_path: Path, content: str = VALID_CONFIG) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_config_and_normalizes_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLASHROUTER_DATA_DIR", str(tmp_path / "data"))
    path = write_config(tmp_path)

    settings = load_config(path)

    assert settings.config_path == path
    assert settings.data_dir == tmp_path / "data"
    assert settings.upstream.base_url == "https://upstream.test/v1"
    assert settings.upstream.headers == {"X-Custom": "custom-value"}
    assert settings.gateway_api_key() == "gateway-secret"
    assert settings.upstream_api_key() == "upstream-secret"
    assert settings.models[0].id == "coding-fast"
    assert settings.models[0].upstream_model == "real/model"


def test_environment_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLASHROUTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FLASHROUTER_PORT", "9999")
    monkeypatch.setenv("FLASHROUTER_GATEWAY_API_KEY", "env-gateway")
    monkeypatch.setenv("FLASHROUTER_UPSTREAM_BASE_URL", "https://env-upstream.test")
    monkeypatch.setenv("FLASHROUTER_UPSTREAM_API_KEY", "env-upstream")
    monkeypatch.setenv("FLASHROUTER_UPSTREAM_TITLE", "Env Router")
    path = write_config(tmp_path)

    settings = load_config(path)

    assert settings.server.port == 9999
    assert settings.gateway_api_key() == "env-gateway"
    assert settings.upstream.base_url == "https://env-upstream.test"
    assert settings.upstream_api_key() == "env-upstream"
    assert settings.upstream.headers["X-OpenRouter-Title"] == "Env Router"


def test_default_upstream_model_uses_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLASHROUTER_DATA_DIR", str(tmp_path))
    path = write_config(
        tmp_path,
        VALID_CONFIG.replace('upstream_model = "real/model"\n', ""),
    )

    settings = load_config(path)

    assert settings.models[0].upstream_model == "coding-fast"


def test_missing_config_is_clear(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Configuration file not found"):
        load_config(tmp_path / "missing.toml")


def test_blank_gateway_key_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLASHROUTER_DATA_DIR", str(tmp_path))
    path = write_config(
        tmp_path,
        VALID_CONFIG.replace('api_key = "gateway-secret"', 'api_key = ""'),
    )

    with pytest.raises(ConfigError, match="api_key"):
        load_config(path)


def test_duplicate_model_ids_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLASHROUTER_DATA_DIR", str(tmp_path))
    path = write_config(
        tmp_path,
        VALID_CONFIG
        + """
[[models]]
id = "coding-fast"
upstream_model = "other/model"
""",
    )

    with pytest.raises(ConfigError, match="duplicate model ids"):
        load_config(path)


def test_forbidden_custom_header_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLASHROUTER_DATA_DIR", str(tmp_path))
    path = write_config(
        tmp_path,
        VALID_CONFIG.replace('X-Custom = "custom-value"', 'Authorization = "oops"'),
    )

    with pytest.raises(ConfigError, match="must not contain"):
        load_config(path)
