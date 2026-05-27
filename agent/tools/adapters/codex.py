"""Codex CLI → tool.md adapter."""

import json
from pathlib import Path

import yaml
import structlog

from agent.tools.loader import ToolDefinition, Capability

logger = structlog.get_logger()


def convert_codex_config(config_path: Path) -> list[ToolDefinition]:
    """Convert Codex CLI config.yaml to tool definitions (MCP servers only for now)."""
    if not config_path.exists():
        from agent.errors import ImportError_
        raise ImportError_(f"Codex config not found: {config_path}")

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        from agent.errors import ImportError_
        raise ImportError_(f"Invalid Codex config: {e}")

    results = []
    mcp_servers = config.get("mcpServers", {})
    for name, cfg in mcp_servers.items():
        command = cfg.get("command", str(cfg))
        results.append(ToolDefinition(
            name=f"codex-{name}",
            version="0.1.0",
            description=f"Codex MCP server: {name}",
            objects=["general"],
            capabilities=[Capability(
                name=name,
                description=f"MCP tool from Codex: {command}",
                parameters={},
            )],
            runtime="mcp",
            source="codex-plugin",
            source_command=command,
            body=f"Imported from Codex config: {name}",
        ))

    logger.info("codex_imported", tools=len(results))
    return results


def convert_codex_plugin(plugin_dir: Path) -> list[ToolDefinition]:
    """Convert a Codex CLI plugin directory to tool definitions."""
    if not plugin_dir.is_dir():
        from agent.errors import ImportError_
        raise ImportError_(f"Codex plugin directory not found: {plugin_dir}")

    plugin_json = plugin_dir / "codex-plugin.json"
    metadata = {}
    if plugin_json.exists():
        try:
            metadata = json.loads(plugin_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    name = metadata.get("name", plugin_dir.name)
    description = metadata.get("description", f"Codex plugin: {name}")

    return [ToolDefinition(
        name=f"codex-{name}",
        version=metadata.get("version", "0.1.0"),
        description=description,
        objects=["general"],
        capabilities=[Capability(
            name=name,
            description=description,
            parameters={},
        )],
        runtime="import",
        source="codex-plugin",
        source_command=str(plugin_dir),
        body=f"Imported from Codex plugin: {plugin_dir.name}",
    )]
