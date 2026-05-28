"""Tests that built-in tool.md files load correctly."""

from pathlib import Path

from therain2020.tools import load_builtin_tools
from therain2020.tools_md import load_tool_from_file


def test_file_reader_tool():
    md_path = Path(__file__).parent.parent / "therain2020" / "domain" / "tools" / "file-reader.md"
    tool = load_tool_from_file(md_path)
    assert tool.name == "filesystem"
    assert len(tool.capabilities) == 5
    cap_names = [c.name for c in tool.capabilities]
    assert "read" in cap_names
    assert "write" in cap_names
    assert "list_files" in cap_names


def test_browser_control_tool():
    md_path = Path(__file__).parent.parent / "therain2020" / "domain" / "tools" / "browser-control.md"
    tool = load_tool_from_file(md_path)
    assert tool.name == "browser"
    assert len(tool.capabilities) >= 8
    cap_names = [c.name for c in tool.capabilities]
    assert "capture_screenshot" in cap_names
    assert "click_at_xy" in cap_names
    assert "page_info" in cap_names


def test_load_builtin_tools():
    registry = load_builtin_tools()
    tools = registry.list_all()
    assert len(tools) >= 2

    # filesystem tools
    fs = registry.get("filesystem")
    assert fs is not None
    assert len(fs.to_openai_tools()) == 5

    # browser tools
    browser = registry.get("browser")
    assert browser is not None
    assert len(browser.to_openai_tools()) >= 8
