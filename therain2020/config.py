"""Provider config persistence — ~/.therain2020-agent/config.yaml

Env vars override file values, so CI/docker still works.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".therain2020-agent"
CONFIG_PATH = CONFIG_DIR / "config.yaml"

DEFAULT_CONFIG = {
    "provider": None,
    "model": None,
    "providers": {},
}

# (key, label, env_var, default_model, base_url, cost_per_1k)
PROVIDER_REGISTRY = [  # noqa: E501
    # ---- International ----
    ("openai",      "OpenAI",           "OPENAI_API_KEY",     "gpt-4o-mini",
     "https://api.openai.com/v1", 0.15),
    ("openai-l",    "OpenAI (large)",   "OPENAI_API_KEY",     "gpt-4o",
     "https://api.openai.com/v1", 2.50),
    ("anthropic",   "Anthropic",        "ANTHROPIC_API_KEY",  "claude-haiku-4-5-20251001",
     None, 0.80),
    ("anthropic-l", "Anthropic(large)", "ANTHROPIC_API_KEY",
     "claude-sonnet-4-6-20250514", None, 3.00),
    ("gemini",      "Google Gemini",    "GEMINI_API_KEY",     "gemini-2.0-flash",
     "https://generativelanguage.googleapis.com/v1beta", 0.08),
    ("groq",        "Groq",             "GROQ_API_KEY",       "llama-3.3-70b-versatile",
     "https://api.groq.com/openai/v1", 0.05),
    ("mistral",     "Mistral",          "MISTRAL_API_KEY",    "mistral-small-latest",
     "https://api.mistral.ai/v1", 0.10),
    ("together",    "Together AI",      "TOGETHER_API_KEY",
     "meta-llama/Llama-3.3-70B-Instruct-Turbo",
     "https://api.together.xyz/v1", 0.12),
    ("cerebras",    "Cerebras",         "CEREBRAS_API_KEY",   "llama3.1-8b",
     "https://api.cerebras.ai/v1", 0.10),
    ("xai",         "xAI (Grok)",       "XAI_API_KEY",        "grok-beta",
     "https://api.x.ai/v1", 0.30),
    ("cohere",      "Cohere",           "COHERE_API_KEY",     "command-r-plus",
     "https://api.cohere.com/v2", 0.50),
    ("perplexity",  "Perplexity",       "PERPLEXITY_API_KEY", "sonar-pro",
     "https://api.perplexity.ai", 0.20),
    ("fireworks",   "Fireworks AI",     "FIREWORKS_API_KEY",
     "accounts/fireworks/models/llama-v3p1-70b-instruct",
     "https://api.fireworks.ai/inference/v1", 0.30),
    ("replicate",   "Replicate",        "REPLICATE_API_TOKEN",
     "meta/meta-llama-3-70b-instruct",
     "https://api.replicate.com/v1", 0.50),

    # ---- 国内 ----
    ("deepseek",    "DeepSeek 深度求索", "DEEPSEEK_API_KEY",  "deepseek-chat",
     "https://api.deepseek.com/v1", 0.14),
    ("qwen",        "通义千问 Qwen",     "DASHSCOPE_API_KEY",  "qwen-plus",
     "https://dashscope.aliyuncs.com/compatible-mode/v1", 0.10),
    ("qwen-l",      "通义千问 Qwen(large)","DASHSCOPE_API_KEY","qwen-max",
     "https://dashscope.aliyuncs.com/compatible-mode/v1", 1.00),
    ("zhipu",       "智谱 GLM",          "ZHIPUAI_API_KEY",   "glm-4-flash",
     "https://open.bigmodel.cn/api/paas/v4", 0.05),
    ("zhipu-l",     "智谱 GLM (large)",  "ZHIPUAI_API_KEY",   "glm-4-plus",
     "https://open.bigmodel.cn/api/paas/v4", 1.00),
    ("moonshot",    "月之暗面 Kimi",      "MOONSHOT_API_KEY",  "moonshot-v1-8k",
     "https://api.moonshot.cn/v1", 0.12),
    ("doubao",      "豆包 Doubao",       "ARK_API_KEY",        "ep-2025-doubao-lite",
     "https://ark.cn-beijing.volces.com/api/v3", 0.05),
    ("doubao-l",    "豆包 Doubao(large)","ARK_API_KEY",        "ep-2025-doubao-pro",
     "https://ark.cn-beijing.volces.com/api/v3", 0.50),
    ("baichuan",    "百川 Baichuan",     "BAICHUAN_API_KEY",   "Baichuan4-Turbo",
     "https://api.baichuan-ai.com/v1", 0.10),
    ("minimax",     "MiniMax 海螺",      "MINIMAX_API_KEY",   "abab6.5s-chat",
     "https://api.minimax.chat/v1", 0.05),
    ("yi",          "零一万物 Yi",       "YI_API_KEY",        "yi-large",
     "https://api.lingyiwanwu.com/v1", 0.10),
    ("spark",       "讯飞星火 Spark",    "SPARK_API_KEY",     "generalv3.5",
     None, 0.05),
    ("ernie",       "百度文心 ERNIE",    "QIANFAN_ACCESS_KEY","ernie-speed-128k",
     None, 0.05),

    # ---- Custom / local ----
    ("custom",      "Custom OpenAI-compatible", "",           "gpt-3.5-turbo",
     "http://localhost:11434/v1", 0.00),
]


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return {**DEFAULT_CONFIG, **yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))}
        except Exception:
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        yaml.dump(config, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def get_api_key(provider_name: str, config: dict) -> str | None:
    """Resolve API key: env var first, then config file."""
    for key, label, env_var, model, base_url, cost in PROVIDER_REGISTRY:
        if key == provider_name and env_var:
            if env_val := os.environ.get(env_var):
                return env_val
            break
    prov = config.get("providers", {}).get(provider_name, {})
    return prov.get("api_key") or None


def get_provider_config(provider_name: str, config: dict) -> dict:
    """Get full provider config from registry + saved config."""
    for key, label, env_var, model, base_url, cost in PROVIDER_REGISTRY:
        if key == provider_name:
            prov = config.get("providers", {}).get(provider_name, {})
            return {
                "name": key,
                "label": label,
                "api_key": get_api_key(provider_name, config),
                "base_url": prov.get("base_url") or base_url,
                "model": prov.get("model") or config.get("model") or model,
                "cost_per_1k": cost,
            }
    return {}
