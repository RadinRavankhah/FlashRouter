"""Built-in OpenAI-compatible provider presets.

Every preset speaks the OpenAI Chat Completions API, which is all FlashRouter
needs. Local presets have no authentication; cloud presets require an API key
that the user adds as an account in the dashboard.
"""

from __future__ import annotations

from typing import Any

PRESETS: list[dict[str, Any]] = [
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "local": False,
        "docs": "https://openrouter.ai/keys",
    },
    {
        "id": "groq",
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "local": False,
        "docs": "https://console.groq.com/keys",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "local": False,
        "docs": "https://platform.deepseek.com/api_keys",
    },
    {
        "id": "glm",
        "name": "GLM (Zhipu)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "local": False,
        "docs": "https://open.bigmodel.cn/usercenter/apikeys",
    },
    {
        "id": "minimax",
        "name": "MiniMax",
        "base_url": "https://api.minimax.io/v1",
        "local": False,
        "docs": "https://www.minimax.io/platform/user-center/basic-information",
    },
    {
        "id": "mistral",
        "name": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "local": False,
        "docs": "https://console.mistral.ai/api-keys",
    },
    {
        "id": "gemini",
        "name": "Google Gemini (OpenAI endpoint)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "local": False,
        "docs": "https://aistudio.google.com/app/apikey",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "local": False,
        "docs": "https://platform.openai.com/api-keys",
    },
    {
        "id": "together",
        "name": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "local": False,
        "docs": "https://api.together.xyz/settings/api-keys",
    },
    {
        "id": "cerebras",
        "name": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "local": False,
        "docs": "https://cloud.cerebras.ai",
    },
    {
        "id": "fireworks",
        "name": "Fireworks",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "local": False,
        "docs": "https://fireworks.ai/account/api-keys",
    },
    {
        "id": "nvidia",
        "name": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "local": False,
        "docs": "https://build.nvidia.com",
    },
    {
        "id": "xai",
        "name": "xAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "local": False,
        "docs": "https://console.x.ai",
    },
    {
        "id": "ollama",
        "name": "Ollama (local)",
        "base_url": "http://127.0.0.1:11434/v1",
        "local": True,
        "docs": "https://ollama.com",
    },
    {
        "id": "lmstudio",
        "name": "LM Studio (local)",
        "base_url": "http://127.0.0.1:1234/v1",
        "local": True,
        "docs": "https://lmstudio.ai",
    },
    {
        "id": "llamacpp",
        "name": "llama.cpp server (local)",
        "base_url": "http://127.0.0.1:8080/v1",
        "local": True,
        "docs": "https://github.com/ggml-org/llama.cpp",
    },
    {
        "id": "custom",
        "name": "Custom OpenAI-compatible",
        "base_url": "",
        "local": False,
        "docs": "",
    },
]

PRESETS_BY_ID = {preset["id"]: preset for preset in PRESETS}


def get_preset(preset_id: str) -> dict[str, Any] | None:
    return PRESETS_BY_ID.get(preset_id)
