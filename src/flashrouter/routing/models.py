"""v0.1 model resolution: a single configured upstream allowlist."""

from __future__ import annotations

from flashrouter.config import ModelConfig
from flashrouter.errors import invalid_request


class ConfiguredModelResolver:
    def __init__(self, models: list[ModelConfig]) -> None:
        self._models = list(models)
        self._by_id = {model.id: model for model in models}

    def resolve(self, model_id: str) -> ModelConfig:
        try:
            return self._by_id[model_id]
        except KeyError as exc:
            raise invalid_request(
                f"Model '{model_id}' is not configured on this gateway",
                code="model_not_found",
                param="model",
            ) from exc

    def list_models(self) -> list[ModelConfig]:
        return list(self._models)
