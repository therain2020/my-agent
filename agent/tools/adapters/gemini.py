"""Gemini CLI → tool.md adapter."""

import json
from pathlib import Path

import structlog

from agent.tools.loader import Capability, ToolDefinition

logger = structlog.get_logger()


def convert_gemini_config(config_path: Path) -> list[ToolDefinition]:
    """Convert Gemini CLI config.json to tool definitions."""
    if not config_path.exists():
        from agent.errors import ImportError_
        raise ImportError_(f"Gemini config not found: {config_path}")

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        from agent.errors import ImportError_
        raise ImportError_(f"Invalid Gemini config JSON: {e}")

    results = []
    mcp_servers = config.get("mcpServers", {})
    for name, cfg in mcp_servers.items():
        command = cfg.get("command", str(cfg))
        results.append(ToolDefinition(
            name=f"gemini-{name}",
            version="0.1.0",
            description=f"Gemini MCP server: {name}",
            objects=["general"],
            capabilities=[Capability(
                name=name,
                description=f"MCP tool from Gemini: {command}",
                parameters={},
            )],
            runtime="mcp",
            source="gemini-ext",
            source_command=command,
            body=f"Imported from Gemini config: {name}",
        ))

    logger.info("gemini_imported", tools=len(results))
    return results


def convert_gemini_extension(ext_dir: Path) -> list[ToolDefinition]:
    """Convert a Gemini CLI extension directory to tool definitions."""
    if not ext_dir.is_dir():
        from agent.errors import ImportError_
        raise ImportError_(f"Gemini extension directory not found: {ext_dir}")

    manifest = ext_dir / "manifest.json"
    metadata = {}
    if manifest.exists():
        try:
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    name = metadata.get("name", ext_dir.name)
    description = metadata.get("description", f"Gemini extension: {name}")

    return [ToolDefinition(
        name=f"gemini-{name}",
        version=metadata.get("version", "0.1.0"),
        description=description,
        objects=["general"],
        capabilities=[Capability(
            name=name,
            description=description,
            parameters={},
        )],
        runtime="import",
        source="gemini-ext",
        source_command=str(ext_dir),
        body=f"Imported from Gemini extension: {ext_dir.name}",
    )]
