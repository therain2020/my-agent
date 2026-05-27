"""MCP Server → tool.md adapter."""


import structlog

from agent.tools.loader import Capability, ToolDefinition

logger = structlog.get_logger()


def detect_transport(source: str) -> str:
    """Detect MCP transport type from command or URL."""
    source = source.strip()
    if source.startswith("http://") or source.startswith("https://"):
        return "sse"
    return "stdio"


def generate_mcp_tool_def(
    server_name: str,
    source: str,
    capabilities: list[Capability],
    server_description: str = "",
) -> ToolDefinition:
    """Generate a ToolDefinition from MCP server metadata."""
    return ToolDefinition(
        name=server_name,
        version="0.1.0",
        description=server_description or f"MCP server: {server_name}",
        objects=_infer_objects_from_caps(capabilities),
        capabilities=capabilities,
        entry_points={},
        dependencies=[],
        runtime="mcp",
        source="mcp-server",
        source_command=source,
        body=server_description or f"MCP server providing {len(capabilities)} tool(s).",
        mcp_transport=detect_transport(source),
    )


def convert_mcp_command(source: str) -> str:
    """Normalize MCP server command string."""
    source = source.strip()
    # Remove leading "mcp:" or "mcp://" if present
    if source.startswith("mcp://"):
        source = source[6:]
    elif source.startswith("mcp:"):
        source = source[4:]
    return source


def _infer_objects_from_caps(capabilities: list[Capability]) -> list[str]:
    """Infer object types from capability names and descriptions."""
    objects = set()
    mapping = {
        "file": ["read_file", "write_file", "list_directory", "search_file",
                 "file", "document", "path"],
        "git": ["git", "commit", "branch", "repository", "diff", "log", "status"],
        "database": ["query", "sql", "table", "schema", "database", "db"],
        "shell": ["execute", "bash", "terminal", "command", "run"],
        "network": ["http", "fetch", "url", "api", "request", "download"],
    }
    for cap in capabilities:
        text = f"{cap.name} {cap.description}".lower()
        for obj, keywords in mapping.items():
            if any(kw in text for kw in keywords):
                objects.add(obj)
    return list(objects) if objects else ["general"]
