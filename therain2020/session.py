"""Session context — bundles the 4 essential services the agent needs.

Includes interactive provider setup fallback when no API key is found.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .constants import MAX_STEPS, WORKSPACE_DIR
from .memory import Memory
from .provider import LLMProvider, detect_providers, route
from .safety import SafetyEngine
from .tools import ToolRegistry, load_builtin_tools


@dataclass
class Session:
    memory: Memory
    tools: ToolRegistry
    safety: SafetyEngine
    provider: LLMProvider
    conversation: list[dict] = field(default_factory=list)
    task_id: str = ""
    workspace: Path = field(default_factory=lambda: WORKSPACE_DIR)
    max_steps: int = MAX_STEPS


def create_session(
    task: str = "",
    workspace: Path | None = None,
    memory_path: str | Path = ":memory:",
    rules_dir: Path | None = None,
    config: dict | None = None,
    interactive: bool = True,
) -> Session:
    """Factory that auto-detects providers and builds a ready-to-use Session.

    If no provider is found and interactive=True, prompts the user
    to pick a provider and specify the API key env var to use.
    """
    if config is None:
        try:
            from .config import load_config
            config = load_config()
        except Exception:
            config = {}

    providers = detect_providers(config)

    if not providers and interactive:
        config = _interactive_setup(config)
        providers = detect_providers(config)

    if not providers:
        raise RuntimeError(
            "No LLM provider available. Run `therain2020 --setup` to configure, "
            "or set an API key environment variable."
        )

    provider = route(task, providers) if task else providers[0]

    from .config import get_api_key  # noqa: E402 — lazy import for test isolation
    prov_name = provider.name
    prov_cfg = config.get("providers", {}).get(prov_name, {})
    api_key = get_api_key(prov_name, config)
    if api_key:
        provider._api_key = api_key
    if prov_cfg.get("base_url"):
        provider._base_url = prov_cfg["base_url"]
    if prov_cfg.get("model"):
        provider.model = prov_cfg["model"]

    ws = workspace or WORKSPACE_DIR
    ws.mkdir(parents=True, exist_ok=True)

    tools = load_builtin_tools()
    tools.scan_generated(ws / ".generated")

    return Session(
        task_id=uuid.uuid4().hex[:12],
        memory=Memory(memory_path),
        tools=tools,
        safety=SafetyEngine(rules_dir),
        provider=provider,
        workspace=ws,
    )


def _interactive_setup(config: dict) -> dict:
    """Prompt user to pick a provider and specify which env var holds the key."""
    from .config import PROVIDER_REGISTRY, save_config

    print()
    print("  No API key found. Let's configure one.")
    print()

    for i, (key, label, _, model, _, _) in enumerate(PROVIDER_REGISTRY):
        print(f"  [{i+1:2d}] {label} — {model}")
    print()

    while True:
        raw = input(f"  Pick provider [1-{len(PROVIDER_REGISTRY)}]: ").strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(PROVIDER_REGISTRY):
                break
        except ValueError:
            pass
        print(f"  Enter 1-{len(PROVIDER_REGISTRY)}")

    key, label, env_var, model, base_url, cost = PROVIDER_REGISTRY[idx]
    default_env = env_var or f"{key.upper()}_API_KEY"

    print()
    print(f"  Provider: {label}")
    print(f"  Default env var name: {default_env}")
    custom = input(f"  Env var name (Enter to use {default_env}): ").strip()
    final_env = custom if custom else default_env

    api_key = os.environ.get(final_env)
    if api_key:
        print(f"  Found {final_env} ({_mask(api_key)})")
    else:
        api_key = input("  API key (paste it now): ").strip()
        if not api_key:
            print("  Skipped. Try again with the --setup flag.")
            return config

    config.setdefault("providers", {}).setdefault(key, {})["api_key"] = api_key
    config["provider"] = key
    save_config(config)

    print(f"  Saved — Active provider: {label}")
    print()
    return config


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "…" + s[-4:]
