"""Cursor rules and MCP → tool.md / behavior_rule adapter."""

import json
from pathlib import Path

import structlog

from agent.tools.loader import ToolDefinition, Capability

logger = structlog.get_logger()


def convert_cursor_mcp(mcp_json_path: Path) -> list[ToolDefinition]:
    """Convert .cursor/mcp.json to tool definitions."""
    if not mcp_json_path.exists():
        from agent.errors import ImportError_
        raise ImportError_(f"Cursor MCP config not found: {mcp_json_path}")

    try:
        config = json.loads(mcp_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        from agent.errors import ImportError_
        raise ImportError_(f"Invalid Cursor MCP JSON: {e}")

    results = []
    mcp_servers = config.get("mcpServers", {})
    for name, cfg in mcp_servers.items():
        command = cfg.get("command", str(cfg))
        results.append(ToolDefinition(
            name=f"cursor-{name}",
            version="0.1.0",
            description=f"Cursor MCP server: {name}",
            objects=["general"],
            capabilities=[Capability(
                name=name,
                description=f"MCP tool from Cursor: {command}",
                parameters={},
            )],
            runtime="mcp",
            source="cursor-mcp",
            source_command=command,
            body=f"Imported from Cursor MCP config: {name}",
        ))

    logger.info("cursor_mcp_imported", tools=len(results))
    return results
