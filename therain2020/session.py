"""Session context — bundles the 4 essential services the agent needs.

Provider config comes from ~/.therain2020-agent/config.yaml.
If not configured, prompts interactively and saves.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .constants import MAX_STEPS, WORKSPACE_DIR
from .memory import Memory
from .provider import LLMProvider, get_configured_provider
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
    """Build a Session from saved config. Falls back to interactive setup."""
    if config is None:
        try:
            from .config import load_config
            config = load_config()
        except Exception:
            config = {}

    provider = get_configured_provider(config)

    if provider is None and interactive:
        config = _interactive_setup(config)
        provider = get_configured_provider(config)

    if provider is None:
        raise RuntimeError(
            "No LLM provider configured. Run `therain2020 --setup`."
        )

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
    """Prompt user to pick provider + enter API key. Save to config."""
    from .config import PROVIDER_REGISTRY, save_config

    print()
    print("  No LLM provider configured. Let's set one up.")
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

    key, label, _, model, base_url, cost = PROVIDER_REGISTRY[idx]
    prov = config.setdefault("providers", {}).setdefault(key, {})

    print()
    print(f"  Provider: {label}")

    # API key
    api_key = input("  API key: ").strip()
    if not api_key:
        print("  Skipped. Run `therain2020 --setup` to configure later.")
        return config
    prov["api_key"] = api_key

    # Model (optional override)
    print(f"  Model [default: {model}]: ", end="")
    m = input().strip()
    if m:
        prov["model"] = m

    # Base URL (optional override)
    if base_url:
        print(f"  Endpoint [default: {base_url}]: ", end="")
        b = input().strip()
        if b:
            prov["base_url"] = b

    config["provider"] = key
    save_config(config)

    print(f"  Saved — Active provider: {label}")
    print()
    return config


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "…" + s[-4:]
