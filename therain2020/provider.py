"""LLM provider abstraction with cost-aware routing.

Thin wrapper over Anthropic / OpenAI SDKs. No pool, no capability
matrix — detect available providers from env vars, route by task
complexity, escalate on failure.

Migrated from: providers/router.py (routing), cli/autodetect.py (detection).
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

# (name, env_var, model_id, cost_per_1k_tokens)
_PROVIDER_REGISTRY: list[tuple[str, str, str, float]] = [
    ("deepseek",     "DEEPSEEK_API_KEY",    "deepseek-chat",      0.14),
    ("openai-mini",  "OPENAI_API_KEY",      "gpt-4o-mini",        0.15),
    ("openai-large", "OPENAI_API_KEY",      "gpt-4o",             2.50),
    ("anthropic-small", "ANTHROPIC_API_KEY", "claude-haiku-4-5-20251001", 0.80),
    ("anthropic-large", "ANTHROPIC_API_KEY", "claude-sonnet-4-6-20250514", 3.00),
]


class LLMProvider:
    """Thin wrapper around an LLM SDK callable."""

    def __init__(self, name: str, model: str, cost_per_1k: float = 0.0):
        self.name = name
        self.model = model
        self.cost_per_1k = cost_per_1k
        self._base_url: str | None = None
        self._api_key: str | None = None

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Call the model. Routes to the correct SDK internally."""
        if "anthropic" in self.name:
            return await _complete_anthropic(
                self.model, messages, tools, tool_choice, max_tokens,
                api_key=self._api_key,
            )
        return await _complete_openai(
            self.model, messages, tools, tool_choice, max_tokens,
            base_url=self._base_url, api_key=self._api_key,
        )

    def token_count(self, text: str) -> int:
        return max(1, len(text.encode("utf-8")) // 4)

    def __repr__(self) -> str:
        return f"LLMProvider({self.name}, {self.model})"


async def _complete_openai(model, messages, tools, tool_choice, max_tokens, base_url=None, api_key=None):
    import openai
    key = api_key or os.environ.get("OPENAI_API_KEY")
    kwargs = {}
    if base_url:
        kwargs["base_url"] = base_url
    client = openai.AsyncOpenAI(api_key=key, **kwargs)
    if "deepseek" in model:
        client = openai.AsyncOpenAI(
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY"),
            base_url=base_url or "https://api.deepseek.com/v1",
        )
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice
    resp = await client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
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


async def _complete_anthropic(model, messages, tools, tool_choice, max_tokens, api_key=None):
    import json

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    system = ""
    user_messages = []
    for m in messages:
        if m["role"] == "system":
            system += m["content"] + "\n"
        else:
            user_messages.append(m)
    kwargs = {
        "model": model,
        "messages": user_messages,
        "max_tokens": max_tokens,
    }
    if system.strip():
        kwargs["system"] = system.strip()
    if tools:
        kwargs["tools"] = _tools_to_anthropic(tools)
    resp = await client.messages.create(**kwargs)
    content_blocks = resp.content
    text = ""
    tool_calls = None
    for block in content_blocks:
        if block.type == "text":
            text += block.text
        elif block.type == "tool_use":
            if tool_calls is None:
                tool_calls = []
            tool_calls.append({
                "id": block.id,
                "type": "function",
                "function": {"name": block.name, "arguments": json.dumps(block.input)},
            })
    return LLMResponse(
        content=text,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else resp.stop_reason,
        model=resp.model,
        tokens_used=resp.usage.input_tokens + resp.usage.output_tokens,
    )


def _tools_to_anthropic(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        f = t["function"]
        out.append({
            "name": f["name"],
            "description": f.get("description", ""),
            "input_schema": f.get("parameters", {"type": "object", "properties": {}}),
        })
    return out


# -- provider detection & routing ---------------------------------------

def detect_providers(config: dict | None = None) -> list[LLMProvider]:
    """Scan env vars + config file for available LLM providers. Sorted by cost.

    Env vars take priority over config file. If a config file specifies an
    active provider, it's included even without an env var.
    """
    if config is None:
        try:
            from .config import load_config
            config = load_config()
        except Exception:
            config = {}

    providers = []
    active_name = config.get("provider")

    for name, env_var, model, cost in _PROVIDER_REGISTRY:
        # Check env var first
        if os.environ.get(env_var):
            providers.append(LLMProvider(name, model, cost_per_1k=cost))
        # Then check config file
        elif config and name in config.get("providers", {}):
            prov = config["providers"][name]
            if prov.get("api_key"):
                cfg_model = prov.get("model") or model
                providers.append(LLMProvider(name, cfg_model, cost_per_1k=cost))

    # If active provider is set but wasn't found via env/config, add it anyway
    if active_name:
        names = {p.name for p in providers}
        base_names = {n.split("-")[0] for n in names}
        if active_name not in names and active_name not in base_names:
            for name, env_var, model, cost in _PROVIDER_REGISTRY:
                if name == active_name:
                    providers.append(LLMProvider(name, model, cost_per_1k=cost))
                    break

    providers.sort(key=lambda p: p.cost_per_1k)
    return providers


def estimate_complexity(task: str) -> TaskComplexity:
    """Keyword-based task complexity assessment (migrated from CostRouter)."""
    tl = task.lower()
    if any(kw in tl for kw in COMPLEX_KW):
        return TaskComplexity.COMPLEX
    if tl.startswith(tuple(SIMPLE_KW)):
        return TaskComplexity.SIMPLE
    return TaskComplexity.MODERATE


def route(task: str, providers: list[LLMProvider]) -> LLMProvider:
    """Pick the right provider for the task.

    SIMPLE  → cheapest available
    COMPLEX → strongest available (last in cost-sorted list)
    MODERATE → middle (or cheapest if only one)
    """
    if not providers:
        raise RuntimeError("No LLM providers available")
    complexity = estimate_complexity(task)
    if complexity == TaskComplexity.SIMPLE or len(providers) == 1:
        return providers[0]
    if complexity == TaskComplexity.COMPLEX:
        return providers[-1]
    # MODERATE: pick the middle
    return providers[len(providers) // 2]


def escalate(current: LLMProvider, providers: list[LLMProvider]) -> LLMProvider | None:
    """Move to the next-stronger provider on failure. Returns None if at top."""
    sorted_providers = sorted(providers, key=lambda p: p.cost_per_1k)
    for i, p in enumerate(sorted_providers):
        if p.name == current.name and i + 1 < len(sorted_providers):
            return sorted_providers[i + 1]
    return None
