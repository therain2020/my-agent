"""Tool registry. 类比: udev + device driver registry."""

from pathlib import Path

import structlog

from .loader import ToolDefinition, parse_tool_md

logger = structlog.get_logger()


class ToolRegistry:
    """Central registry of all tools (builtin + imported).

    类比: udev device database.
    Scans tool directories, parses tool.md, and builds
    capability index for fast lookups.
    """

    def __init__(self, scan_paths: list[str] | None = None):
        self._tools: dict[str, ToolDefinition] = {}
        self._capability_index: dict[str, list[tuple[str, str]]] = {}
        # capability_index: object_type → [(tool_name, capability_name), ...]
        self._scan_paths = scan_paths or ["./tools", "./tools/.generated"]

    def scan(self) -> int:
        """Scan all configured paths for tool.md files and register them.

        Returns number of newly registered tools.
        """
        count = 0
        for scan_path in self._scan_paths:
            path = Path(scan_path)
            if not path.exists():
                continue
            for tool_md in path.rglob("tool.md"):
                try:
                    tool_def = parse_tool_md(tool_md)
                    self.register(tool_def)
                    count += 1
                except Exception as e:
                    logger.error("tool_scan_error", path=str(tool_md), error=str(e))
        return count

    def register(self, tool_def: ToolDefinition) -> None:
        """Register a tool definition. Overwrites if name exists."""
        # Remove old capability index entries
        if tool_def.name in self._tools:
            self._unindex(self._tools[tool_def.name])

        self._tools[tool_def.name] = tool_def
        self._index(tool_def)
        logger.info("tool_registered",
                     name=tool_def.name,
                     source=tool_def.source,
                     capabilities=len(tool_def.capabilities))

    def unregister(self, name: str) -> bool:
        """Remove a tool from the registry. Returns False if not found."""
        tool_def = self._tools.pop(name, None)
        if tool_def is None:
            return False
        self._unindex(tool_def)
        logger.info("tool_unregistered", name=name)
        return True

    def get(self, name: str) -> ToolDefinition | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_all(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def find_by_object(self, object_type: str) -> list[ToolDefinition]:
        """Find tools that can operate on a given object type.

        类比: udev matching — given a device, find the driver.
        """
        tool_names = set()
        for tool_name, _ in self._capability_index.get(object_type, []):
            tool_names.add(tool_name)
        return [self._tools[n] for n in tool_names if n in self._tools]

    def find_capability(self, tool_name: str, cap_name: str):
        """Find a specific capability on a tool."""
        tool = self._tools.get(tool_name)
        if not tool:
            return None
        for cap in tool.capabilities:
            if cap.name == cap_name:
                return cap
        return None

    def list_by_source(self, source: str) -> list[ToolDefinition]:
        """List tools from a specific source (builtin/mcp-server/...)."""
        return [t for t in self._tools.values() if t.source == source]

    def summary(self) -> str:
        """Human-readable summary of registered tools."""
        lines = []
        for t in sorted(self._tools.values(), key=lambda x: x.name):
            caps = ", ".join(c.name for c in t.capabilities)
            lines.append(f"  {t.name:30s} ({t.source:20s})  [{caps}]")
        return "\n".join(lines) if lines else "  (no tools registered)"

    def _index(self, tool_def: ToolDefinition) -> None:
        """Build capability index entries."""
        for cap in tool_def.capabilities:
            # Index by declared objects
            for obj in tool_def.objects:
                self._capability_index.setdefault(obj, []).append(
                    (tool_def.name, cap.name)
                )
            # Also index by tool name itself
            self._capability_index.setdefault(tool_def.name, []).append(
                (tool_def.name, cap.name)
            )

    def _unindex(self, tool_def: ToolDefinition) -> None:
        """Remove capability index entries."""
        for obj in tool_def.objects:
            if obj in self._capability_index:
                self._capability_index[obj] = [
                    (tn, cn) for tn, cn in self._capability_index[obj]
                    if tn != tool_def.name
                ]
        if tool_def.name in self._capability_index:
            del self._capability_index[tool_def.name]
