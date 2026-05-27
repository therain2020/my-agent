"""Tool definition and parser for tool.md files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Capability:
    """A single capability exposed by a tool."""
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    returns: dict = field(default_factory=dict)
    side_effects: list[str] = field(default_factory=list)
    danger_level: str = "low"  # low | medium | high | critical
    timeout_ms: int = 30000
    requires_confirmation: bool = False


@dataclass
class ToolDefinition:
    """A tool definition parsed from tool.md."""
    name: str
    version: str = "0.1.0"
    description: str = ""
    objects: list[str] = field(default_factory=list)
    capabilities: list[Capability] = field(default_factory=list)
    entry_points: dict[str, str] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    runtime: str = "import"  # import | subprocess | mcp
    source: str = "builtin"  # builtin | claude-code-skill | mcp-server | codex-plugin | gemini-ext
    source_command: str = ""  # MCP server command or original skill path
    tool_dir: Optional[Path] = None
    body: str = ""  # Markdown body for LLM context
    mcp_transport: str = "stdio"  # stdio | sse | streamable_http
    raw_frontmatter: dict = field(default_factory=dict)


def parse_tool_md(path: Path) -> ToolDefinition:
    """Parse a tool.md file.

    Expects YAML frontmatter between --- markers, followed by
    markdown body that provides LLM context about the tool.

    Example:
        ---
        name: file-system
        version: "1.0"
        capabilities:
          - name: read_file
            ...
        ---
        # file-system tool
        This tool provides filesystem access...
    """
    content = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(content)

    if not frontmatter:
        raise ValueError(f"No YAML frontmatter found in {path}")

    data = yaml.safe_load(frontmatter)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid frontmatter in {path}")

    caps = []
    for cap_data in data.get("capabilities", []):
        caps.append(Capability(
            name=cap_data.get("name", ""),
            description=cap_data.get("description", ""),
            parameters=cap_data.get("parameters", {}),
            returns=cap_data.get("returns", {}),
            side_effects=cap_data.get("side_effects", []),
            danger_level=cap_data.get("danger_level", "low"),
            timeout_ms=cap_data.get("timeout_ms", 30000),
            requires_confirmation=cap_data.get("requires_confirmation", False),
        ))

    return ToolDefinition(
        name=data.get("name", path.parent.name),
        version=data.get("version", "0.1.0"),
        description=data.get("description", ""),
        objects=data.get("objects", []),
        capabilities=caps,
        entry_points=data.get("entry_points", {}),
        dependencies=data.get("dependencies", []),
        runtime=data.get("runtime", "import"),
        source=data.get("source", "builtin"),
        source_command=data.get("source_command", ""),
        tool_dir=path.parent,
        body=body.strip(),
        mcp_transport=data.get("mcp_transport", "stdio"),
        raw_frontmatter=data,
    )


def generate_tool_md(tool_def: ToolDefinition) -> str:
    """Generate tool.md content from a ToolDefinition."""
    caps = []
    for cap in tool_def.capabilities:
        caps.append({
            "name": cap.name,
            "description": cap.description,
            "parameters": cap.parameters,
            "returns": cap.returns,
            "side_effects": cap.side_effects,
            "danger_level": cap.danger_level,
            "timeout_ms": cap.timeout_ms,
            "requires_confirmation": cap.requires_confirmation,
        })

    frontmatter = yaml.dump({
        "name": tool_def.name,
        "version": tool_def.version,
        "description": tool_def.description,
        "objects": tool_def.objects,
        "capabilities": caps,
        "entry_points": tool_def.entry_points,
        "dependencies": tool_def.dependencies,
        "runtime": tool_def.runtime,
        "source": tool_def.source,
        "source_command": tool_def.source_command,
        "mcp_transport": tool_def.mcp_transport,
    }, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return f"---\n{frontmatter}---\n\n{tool_def.body}".strip()


def _split_frontmatter(content: str) -> tuple[str, str]:
    """Split YAML frontmatter from body."""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return "", content

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return "", content

    frontmatter = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1:])
    return frontmatter, body
