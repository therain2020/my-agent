"""Browser Harness adapter. Registers browser tools into the agent tool system.

类比: filesystem driver registration.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from agent.tools.loader import parse_tool_md

logger = structlog.get_logger()


class BrowserHarnessAdapter:
    """Adapter that registers browser tools into the agent's tool registry."""

    def __init__(self, registry: object) -> None:
        self.registry = registry

    def register(self, tools_dir: Path | None = None) -> int:
        """Register browser tools.

        Scans agent/tools/browser/ for tool.md and registers all capabilities.
        Returns number of tools registered.
        """
        if tools_dir is None:
            tools_dir = Path(__file__).parent.parent / "browser"

        tool_md = tools_dir / "tool.md"
        if not tool_md.exists():
            logger.warning("browser_harness_tool_md_not_found", path=str(tool_md))
            return 0

        try:
            tool_def = parse_tool_md(tool_md)
            self.registry.register(tool_def)
            logger.info(
                "browser_harness_registered",
                capabilities=len(tool_def.capabilities),
            )
            return 1
        except Exception as e:
            logger.error("browser_harness_register_failed", error=str(e))
            return 0
