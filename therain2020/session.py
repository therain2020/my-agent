"""Session context — bundles the 4 essential services the agent needs.

No daemon, no consolidation manager, no pattern miner, no skill
lifecycle. Just data + the services that matter.
"""

from __future__ import annotations

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
) -> Session:
    """Factory that auto-detects providers and builds a ready-to-use Session."""
    providers = detect_providers()
    if not providers:
        raise RuntimeError(
            "No LLM provider available. "
            "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or DEEPSEEK_API_KEY."
        )

    provider = route(task, providers) if task else providers[0]
    ws = workspace or Path(".agent")
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
