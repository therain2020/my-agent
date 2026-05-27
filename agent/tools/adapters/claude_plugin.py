"""Claude Code .claude-plugin/ → N tool.md adapter."""

import json
from pathlib import Path

import structlog

from agent.tools.loader import ToolDefinition

from .claude_skill import convert_claude_skill

logger = structlog.get_logger()


def convert_claude_plugin(plugin_path: Path) -> list[ToolDefinition]:
    """Convert a Claude Code .claude-plugin/ directory to tool definitions.

    A plugin can contain multiple skills + hooks.
    Each skill/ becomes a tool or role.
    Hooks/ become lifecycle probes.
    """
    if not plugin_path.is_dir():
        from agent.errors import ImportError_
        raise ImportError_(f"Plugin path must be a directory: {plugin_path}")

    plugin_json = plugin_path / "plugin.json"
    metadata = {}
    if plugin_json.exists():
        try:
            metadata = json.loads(plugin_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    results = []

    # 1. Recurse into skills/
    skills_dir = plugin_path / "skills"
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir():
                try:
                    results.extend(convert_claude_skill(skill_dir))
                except Exception as e:
                    logger.warning("plugin_skill_skip", path=str(skill_dir), error=str(e))

    # 2. Hooks/ → lifecycle probe (stub)
    hooks_dir = plugin_path / "hooks"
    if hooks_dir.exists():
        for hook_file in hooks_dir.iterdir():
            if hook_file.suffix in (".sh", ".py", ".js"):
                hook_name = hook_file.stem.replace("-", "_")
                logger.info("plugin_hook_detected",
                            name=hook_name,
                            path=str(hook_file),
                            note="Hook imported as probe stub (not yet executed)")

    logger.info("plugin_converted",
                 name=metadata.get("name", plugin_path.name),
                 tools=len(results))
    return results
