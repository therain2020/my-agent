"""Tests that built-in tool.md files load correctly."""

from pathlib import Path

from therain2020.tools import load_builtin_tools
from therain2020.tools_md import load_tool_from_file


def test_bash_tool():
    md_path = Path(__file__).parent.parent / "therain2020" / "domain" / "tools" / "bash.md"
    tool = load_tool_from_file(md_path)
    assert tool.name == "bash"
    cap_names = [c.name for c in tool.capabilities]
    assert "run" in cap_names
    assert "read" in cap_names
    assert "write" in cap_names
    assert "delete" in cap_names


def test_browser_control_tool():
    md_path = Path(__file__).parent.parent / "therain2020" / "domain" / "tools" / "browser-control.md"
    tool = load_tool_from_file(md_path)
    assert tool.name == "browser"
    cap_names = [c.name for c in tool.capabilities]
    assert "capture_screenshot" in cap_names
    assert "new_tab" in cap_names


def test_load_builtin_tools():
    registry = load_builtin_tools()
    tools = registry.list_all()
    assert len(tools) >= 2
    assert registry.get("bash") is not None
    assert registry.get("browser") is not None
