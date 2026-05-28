"""Auto-detect LLM providers from environment variables.

Like Claude Code, which auto-detects auth from env/config without
requiring manual `provider add`. User sets API key once via env var,
the agent picks it up automatically on every startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import structlog

from agent.providers import LLMProvider, ProviderConfig

logger = structlog.get_logger()


@dataclass
class EnvProvider:
    """A provider that can be auto-detected from environment variables."""

    name: str
    adapter: str  # anthropic | openai | deepseek | custom
    key_env: str
    base_url: str = ""
    default_model: str = ""


# Ordered by preference — first found wins
_KNOWN_PROVIDERS = [
    EnvProvider(
        name="deepseek",
        adapter="deepseek",
        key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
    ),
    EnvProvider(
        name="anthropic",
        adapter="anthropic",
        key_env="ANTHROPIC_API_KEY",
        default_model="claude-sonnet-4-6",
    ),
    EnvProvider(
        name="openai",
        adapter="openai",
        key_env="OPENAI_API_KEY",
        default_model="gpt-4o",
    ),
    EnvProvider(
        name="openai",
        adapter="openai",
        key_env="AZURE_OPENAI_API_KEY",
        default_model="gpt-4o",
    ),
    EnvProvider(
        name="qwen",
        adapter="custom",
        key_env="ALI_TONGYI_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
    ),
    EnvProvider(
        name="gemini",
        adapter="openai",
        key_env="GEMINI_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.5-flash",
    ),
    EnvProvider(
        name="moonshot",
        adapter="custom",
        key_env="MOONSHOT_API_KEY",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
    ),
    EnvProvider(
        name="zhipu",
        adapter="custom",
        key_env="GLM_API_KEY",
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        default_model="glm-4",
    ),
]


def detect_from_env() -> tuple[LLMProvider | None, ProviderConfig | None, str]:
    """Scan environment for known API keys. Returns first found.

    Returns (provider, config, source_description).
    """
    for ep in _KNOWN_PROVIDERS:
        key = os.environ.get(ep.key_env, "")
        if not key:
            continue

        logger.info(
            "autodetect_found",
            provider=ep.name,
            env_var=ep.key_env,
            model=ep.default_model,
        )

        config = ProviderConfig(
            name=ep.name,
            model=ep.default_model,
            base_url=ep.base_url if ep.base_url else None,
            api_key=key,
        )

        # Build the right provider
        if ep.adapter == "anthropic":
            from agent.providers.anthropic import AnthropicProvider
            provider = AnthropicProvider(config)
        elif ep.adapter == "openai":
            from agent.providers.openai import OpenAIProvider
            provider = OpenAIProvider(config)
        elif ep.adapter == "deepseek":
            from agent.providers.openai import OpenAIProvider
            # DeepSeek uses OpenAI-compatible API
            config = ProviderConfig(
                name=ep.name,
                model=ep.default_model,
                base_url=ep.base_url,
                api_key=key,
            )
            provider = OpenAIProvider(config)
        else:
            from agent.providers.custom import CustomProvider
            provider = CustomProvider(config)

        return provider, config, f"{ep.name} (via ${ep.key_env})"

    return None, None, ""


def detect_all_from_env() -> list[tuple[LLMProvider, ProviderConfig]]:
    """Scan for ALL available providers from environment. Returns all found."""
    results = []
    for ep in _KNOWN_PROVIDERS:
        key = os.environ.get(ep.key_env, "")
        if not key:
            continue
        config = ProviderConfig(
            name=ep.name,
            model=ep.default_model,
            base_url=ep.base_url if ep.base_url else None,
            api_key=key,
        )
        if ep.adapter == "anthropic":
            from agent.providers.anthropic import AnthropicProvider
            results.append((AnthropicProvider(config), config))
        elif ep.adapter in ("openai", "deepseek"):
            from agent.providers.openai import OpenAIProvider
            results.append((OpenAIProvider(config), config))
        else:
            from agent.providers.custom import CustomProvider
            results.append((CustomProvider(config), config))
    return results
