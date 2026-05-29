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

class LLMProvider:
    """Thin wrapper around an LLM SDK callable."""

    def __init__(self, name: str, model: str,
                 cost_per_1k: float = 0.0, base_url: str | None = None):
        self.name = name
        self.model = model
        self.cost_per_1k = cost_per_1k
        self._base_url = base_url
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


def _build_client(key, base_url, default_api_key):
    """Build an AsyncOpenAI client with proxy support from net_proxy env var."""
    import httpx
    import openai
    proxy_url = os.environ.get("net_proxy") or os.environ.get("HTTP_PROXY")
    http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None
    return openai.AsyncOpenAI(
        api_key=key or os.environ.get(default_api_key),
        base_url=base_url,
        http_client=http_client,
    )


async def _complete_openai(model, messages, tools, tool_choice, max_tokens, base_url=None, api_key=None):
    # Route to the correct key + base URL per provider
    if "deepseek" in model:
        client = _build_client(api_key, base_url or "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY")
    elif "qwen" in model:
        client = _build_client(api_key,
                               base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
                               "DASHSCOPE_API_KEY")
    elif "glm" in model:
        client = _build_client(api_key, base_url or "https://open.bigmodel.cn/api/paas/v4", "ZHIPUAI_API_KEY")
    elif "moonshot" in model:
        client = _build_client(api_key, base_url or "https://api.moonshot.cn/v1", "MOONSHOT_API_KEY")
    elif "doubao" in model or "ep-" in model:
        client = _build_client(api_key,
                               base_url or "https://ark.cn-beijing.volces.com/api/v3", "ARK_API_KEY")
    else:
        client = _build_client(api_key, base_url, "OPENAI_API_KEY")
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

    Uses the canonical PROVIDER_REGISTRY from config.py so the setup wizard
    and runtime detection agree on provider keys and env var names.
    """
    from .config import PROVIDER_REGISTRY  # canonical source

    if config is None:
        try:
            from .config import load_config
            config = load_config()
        except Exception:
            config = {}

    providers = []
    active_name = config.get("provider") if config else None

    for name, label, env_var, model, base_url, cost in PROVIDER_REGISTRY:
        # Check env var first (uses the DEFAULT env var from registry)
        if env_var and os.environ.get(env_var):
            providers.append(LLMProvider(name, model,
                                         cost_per_1k=cost, base_url=base_url))
        # Then check config file (api_key stored from --setup)
        elif config and name in config.get("providers", {}):
            prov = config["providers"][name]
            if prov.get("api_key"):
                cfg_model = prov.get("model") or model
                cfg_base = prov.get("base_url") or base_url
                providers.append(LLMProvider(name, cfg_model,
                                             cost_per_1k=cost, base_url=cfg_base))

    # If active provider has a custom env var (e.g. ALI_TONGYI_KEY instead
    # of DASHSCOPE_API_KEY), the loop above would've missed it. Check config again.
    if active_name:
        names = {p.name for p in providers}
        if active_name not in names:
            prov_cfg = (config or {}).get("providers", {}).get(active_name, {})
            if prov_cfg.get("api_key"):
                for name, label, env_var, model, base_url, cost in PROVIDER_REGISTRY:
                    if name == active_name:
                        cfg_model = prov_cfg.get("model") or model
                        cfg_base = prov_cfg.get("base_url") or base_url
                        providers.append(LLMProvider(name, cfg_model,
                                                     cost_per_1k=cost, base_url=cfg_base))
                        break
                else:
                    providers.append(LLMProvider(
                        active_name, prov_cfg.get("model", "unknown"),
                        cost_per_1k=prov_cfg.get("cost", 0.0)))

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
