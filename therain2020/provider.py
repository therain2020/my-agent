"""LLM provider — thin wrapper with proxy support.

Config file (~/.therain2020-agent/config.yaml) is the single source
of truth. No env var probing — user configured everything in --setup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class TaskComplexity(Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict] | None = None
    finish_reason: str = "stop"
    model: str = ""
    tokens_used: int = 0


SIMPLE_KW = frozenset([
    "read", "show", "list", "get", "display", "print", "check",
    "what", "how many", "count", "find", "search",
])

COMPLEX_KW = frozenset([
    "refactor", "rewrite", "architecture", "design", "debug",
    "optimise", "optimize", "analyze", "analyse", "review",
    "investigate", "fix", "secure", "migrate",
])


class LLMProvider:
    """Thin wrapper. All config comes from the Session factory."""

    def __init__(self, name: str, model: str, cost_per_1k: float = 0.0,
                 base_url: str | None = None, api_key: str | None = None):
        self.name = name
        self.model = model
        self.cost_per_1k = cost_per_1k
        self._base_url = base_url
        self._api_key = api_key

    async def complete(self, messages, tools=None, tool_choice="auto",
                       max_tokens=4096) -> LLMResponse:
        if "anthropic" in self.name:
            return await _complete_anthropic(
                self.model, messages, tools, max_tokens, self._api_key)
        return await _complete_openai(
            self.model, messages, tools, max_tokens,
            self._base_url, self._api_key)

    def token_count(self, text: str) -> int:
        return max(1, len(text.encode("utf-8")) // 4)

    def __repr__(self) -> str:
        return f"LLMProvider({self.name}, {self.model})"


# -- HTTP client builders ------------------------------------------------

def _proxy_url() -> str | None:
    raw = os.environ.get("net_proxy") or os.environ.get("HTTP_PROXY")
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    return raw


def _build_openai_client(api_key: str, base_url: str | None) -> openai.AsyncOpenAI:  # type: ignore[name-defined]  # noqa: F821
    import httpx
    import openai
    proxy = _proxy_url()
    http_client = httpx.AsyncClient(proxy=proxy) if proxy else None
    return openai.AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=http_client)


# -- completion helpers --------------------------------------------------

async def _complete_openai(model, messages, tools, max_tokens, base_url, api_key):
    client = _build_openai_client(api_key, base_url)
    kw = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        kw["tools"] = tools
        kw["tool_choice"] = "auto"
    resp = await client.chat.completions.create(**kw)  # type: ignore[arg-type]
    choice = resp.choices[0]
    tool_calls = None
    if choice.message.tool_calls:
        tool_calls = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in choice.message.tool_calls
        ]
    return LLMResponse(
        content=choice.message.content or "",
        tool_calls=tool_calls,
        finish_reason=choice.finish_reason or "stop",
        model=resp.model,
        tokens_used=resp.usage.total_tokens if resp.usage else 0,
    )


async def _complete_anthropic(model, messages, tools, max_tokens, api_key):
    import json

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    system = ""
    user_msgs = []
    for m in messages:
        if m["role"] == "system":
            system += m["content"] + "\n"
        else:
            user_msgs.append(m)
    kw = {"model": model, "messages": user_msgs, "max_tokens": max_tokens}
    if system.strip():
        kw["system"] = system.strip()
    if tools:
        kw["tools"] = [
            {"name": t["function"]["name"],
             "description": t["function"].get("description", ""),
             "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}})}
            for t in tools
        ]
    resp = await client.messages.create(**kw)
    text = ""
    tool_calls = None
    for block in resp.content:
        if block.type == "text":
            text += block.text
        elif block.type == "tool_use":
            if tool_calls is None:
                tool_calls = []
            tool_calls.append({
                "id": block.id, "type": "function",
                "function": {"name": block.name, "arguments": json.dumps(block.input)},
            })
    return LLMResponse(
        content=text,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else resp.stop_reason,
        model=resp.model,
        tokens_used=resp.usage.input_tokens + resp.usage.output_tokens,
    )


# -- provider config (from config file only) ----------------------------

def get_configured_provider(config: dict | None = None) -> LLMProvider | None:
    """Read the active provider from config file. No env var probing."""
    if config is None:
        try:
            from .config import load_config
            config = load_config()
        except Exception:
            config = {}

    active = config.get("provider") if config else None
    if not active:
        return None

    # Look up from config first, then from registry for defaults
    prov_cfg = (config or {}).get("providers", {}).get(active, {})
    api_key = prov_cfg.get("api_key")
    if not api_key:
        return None

    model = prov_cfg.get("model") or "gpt-3.5-turbo"
    base_url = prov_cfg.get("base_url")
    cost = prov_cfg.get("cost", 0.0)

    # Fall back to registry for base_url / model / cost defaults
    if not base_url or not model or not cost:
        try:
            from .config import PROVIDER_REGISTRY
            for name, label, env_var, def_model, def_base, def_cost in PROVIDER_REGISTRY:
                if name == active:
                    if not model or model == "gpt-3.5-turbo":
                        model = def_model
                    if not base_url:
                        base_url = def_base
                    if not cost:
                        cost = def_cost
                    break
        except Exception:
            pass

    return LLMProvider(active, model, cost_per_1k=cost,
                       base_url=base_url, api_key=api_key)


# -- routing ------------------------------------------------------------

def estimate_complexity(task: str) -> TaskComplexity:
    tl = task.lower()
    if any(kw in tl for kw in COMPLEX_KW):
        return TaskComplexity.COMPLEX
    if tl.startswith(tuple(SIMPLE_KW)):
        return TaskComplexity.SIMPLE
    return TaskComplexity.MODERATE


def route(task: str, providers: list[LLMProvider]) -> LLMProvider:
    if not providers:
        raise RuntimeError("No LLM providers available")
    if estimate_complexity(task) == TaskComplexity.COMPLEX and len(providers) > 1:
        return providers[-1]
    return providers[0]
