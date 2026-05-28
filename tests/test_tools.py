"""Tests for tools_md.py and tools.py."""

from pathlib import Path

import pytest

from therain2020.tools import ToolRegistry
from therain2020.tools_md import load_tool_from_file, parse_tool_md

SAMPLE_TOOL_MD = """---
name: file-reader
version: 1.0.0
objects: [file]
capabilities:
  - name: read
    description: Read the contents of a file
    parameters:
      path: string (required) — Absolute or relative file path
      encoding: string — File encoding, default utf-8
    verify:
      type: return_code
      expected: 0
---

# file-reader

Reads files from the filesystem.
"""


class TestParseToolMd:
    def test_parse_basic(self):
        tool = parse_tool_md(SAMPLE_TOOL_MD)
        assert tool.name == "file-reader"
        assert tool.version == "1.0.0"
        assert tool.objects == ["file"]

    def test_parse_capabilities(self):
        tool = parse_tool_md(SAMPLE_TOOL_MD)
        assert len(tool.capabilities) == 1
        cap = tool.capabilities[0]
        assert cap.name == "read"
        assert "file" in cap.description.lower()

    def test_parse_parameters(self):
        tool = parse_tool_md(SAMPLE_TOOL_MD)
        cap = tool.capabilities[0]
        assert len(cap.parameters) == 2
        path_param = cap.parameters[0]
        assert path_param.name == "path"
        assert path_param.type == "string"
        assert path_param.required is True
        encoding_param = cap.parameters[1]
        assert encoding_param.name == "encoding"
        assert encoding_param.required is False

    def test_parse_body(self):
        tool = parse_tool_md(SAMPLE_TOOL_MD)
        assert "Reads files from the filesystem" in tool.body

    def test_to_openai_tools(self):
        tool = parse_tool_md(SAMPLE_TOOL_MD)
        oai = tool.to_openai_tools()
        assert len(oai) == 1
        assert oai[0]["type"] == "function"
        assert oai[0]["function"]["name"] == "file-reader__read"
        assert oai[0]["function"]["parameters"]["required"] == ["path"]

    def test_parse_from_file(self, tmp_path):
        md_file = tmp_path / "test-tool.md"
        md_file.write_text(SAMPLE_TOOL_MD, encoding="utf-8")
        tool = load_tool_from_file(md_file)
        assert tool.name == "file-reader"
        assert tool.source_path == md_file

    def test_parse_no_frontmatter_raises(self):
        with pytest.raises(ValueError):
            parse_tool_md("Just some text")

    def test_parse_missing_name_raises(self):
        with pytest.raises(ValueError):
            parse_tool_md("---\nversion: 1.0\n---\nbody")


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = parse_tool_md(SAMPLE_TOOL_MD)
        reg.register(tool)
        assert reg.get("file-reader") is tool
        assert reg.get("nonexistent") is None

    def test_find_for_object(self):
        reg = ToolRegistry()
        tool = parse_tool_md(SAMPLE_TOOL_MD)
        reg.register(tool)
        results = reg.find_for_object("file")
        assert len(results) == 1
        assert results[0].name == "file-reader"
        assert reg.find_for_object("database") == []

    def test_list_all(self):
        reg = ToolRegistry()
        reg.register(parse_tool_md(SAMPLE_TOOL_MD))
        assert len(reg.list_all()) == 1

    def test_scan_directory(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "tool-a.md").write_text(SAMPLE_TOOL_MD, encoding="utf-8")
        reg = ToolRegistry()
        reg.scan_directory(tools_dir)
        assert reg.get("file-reader") is not None

    def test_scan_empty_directory(self, tmp_path):
        tools_dir = tmp_path / "empty"
        tools_dir.mkdir()
        reg = ToolRegistry()
        reg.scan_directory(tools_dir)
        assert len(reg.list_all()) == 0

    def test_scan_nonexistent_directory(self):
        reg = ToolRegistry()
        reg.scan_directory(Path("/nonexistent/path"))
        assert len(reg.list_all()) == 0
