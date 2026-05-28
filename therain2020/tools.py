"""Thin tool registry — scan, register, lookup by object type.

Agent-authored tools live in `workspace/.generated/*.md` and are
loaded automatically on the next run. No evolution manager, no
import supervisor — the agent edits files, the registry loads them.
"""

from __future__ import annotations

from pathlib import Path

from .tools_md import ToolDef, load_tool_from_file


class ToolRegistry:
    """Dict-based registry indexed by tool name and object type."""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
        self._by_object: dict[str, list[str]] = {}

    def register(self, tool: ToolDef):
        self._tools[tool.name] = tool
        for obj in tool.objects:
            self._by_object.setdefault(obj, []).append(tool.name)

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def find_for_object(self, object_type: str) -> list[ToolDef]:
        names = self._by_object.get(object_type, [])
        return [self._tools[n] for n in names if n in self._tools]

    def list_all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def scan_directory(self, dir: Path):
        if not dir.is_dir():
            return
        for path in sorted(dir.glob("*.md")):
            try:
                self.register(load_tool_from_file(path))
            except Exception:
                pass

    def scan_generated(self, workspace: Path):
        gen_dir = workspace / ".generated"
        self.scan_directory(gen_dir)


def load_builtin_tools() -> ToolRegistry:
    """Load tools shipped with the package (therain2020/domain/tools/)."""
    registry = ToolRegistry()
    builtin = Path(__file__).resolve().parent / "domain" / "tools"
    registry.scan_directory(builtin)
    return registry
