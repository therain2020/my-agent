"""Tests for tool registry."""

from agent.tools.loader import Capability, ToolDefinition
from agent.tools.registry import ToolRegistry


def make_tool(name: str, objects: list[str], caps: list[str], source: str = "builtin") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        objects=objects,
        capabilities=[Capability(name=c, description=c) for c in caps],
        source=source,
    )


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry(scan_paths=[])
        reg.register(make_tool("test", ["file"], ["read", "write"]))
        tool = reg.get("test")
        assert tool is not None
        assert tool.name == "test"
        assert len(tool.capabilities) == 2

    def test_list_all(self):
        reg = ToolRegistry(scan_paths=[])
        reg.register(make_tool("a", ["file"], ["r"]))
        reg.register(make_tool("b", ["git"], ["commit"]))
        assert len(reg.list_all()) == 2

    def test_find_by_object(self):
        reg = ToolRegistry(scan_paths=[])
        reg.register(make_tool("file-tool", ["file"], ["read"]))
        reg.register(make_tool("db-tool", ["database"], ["query"]))

        file_tools = reg.find_by_object("file")
        assert len(file_tools) == 1
        assert file_tools[0].name == "file-tool"

        db_tools = reg.find_by_object("database")
        assert len(db_tools) == 1
        assert db_tools[0].name == "db-tool"

    def test_find_capability(self):
        reg = ToolRegistry(scan_paths=[])
        cap = Capability(name="special", description="A special cap")
        tool = ToolDefinition(
            name="multi", objects=["general"],
            capabilities=[Capability(name="a"), cap, Capability(name="b")],
        )
        reg.register(tool)

        found = reg.find_capability("multi", "special")
        assert found is cap

        not_found = reg.find_capability("multi", "nonexistent")
        assert not_found is None

    def test_unregister(self):
        reg = ToolRegistry(scan_paths=[])
        reg.register(make_tool("temp", ["x"], ["y"]))
        assert reg.get("temp") is not None

        reg.unregister("temp")
        assert reg.get("temp") is None

    def test_list_by_source(self):
        reg = ToolRegistry(scan_paths=[])
        reg.register(make_tool("builtin-a", [], [], source="builtin"))
        reg.register(make_tool("mcp-a", [], [], source="mcp-server"))

        builtin = reg.list_by_source("builtin")
        mcp = reg.list_by_source("mcp-server")
        assert len(builtin) == 1
        assert len(mcp) == 1

    def test_overwrite_on_register(self):
        reg = ToolRegistry(scan_paths=[])
        reg.register(make_tool("dup", ["a"], ["x"]))
        reg.register(make_tool("dup", ["b"], ["y", "z"]))
        tool = reg.get("dup")
        assert len(tool.capabilities) == 2
        assert tool.objects == ["b"]

    def test_summary(self):
        reg = ToolRegistry(scan_paths=[])
        reg.register(make_tool("fs", ["file"], ["read"]))
        summary = reg.summary()
        assert "fs" in summary
        assert "builtin" in summary
