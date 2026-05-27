"""Tests for tool.md loader."""

import tempfile
from pathlib import Path

from agent.tools.loader import (
    ToolDefinition,
    Capability,
    parse_tool_md,
    generate_tool_md,
    _split_frontmatter,
)


SAMPLE_TOOL_MD = """---
name: test-tool
version: "1.0"
description: A test tool
objects: [file, database]
capabilities:
  - name: do_thing
    description: Does something
    parameters:
      input: { type: string, required: true }
    returns: { type: string }
    danger_level: medium
  - name: do_other
    description: Does something else
    parameters: {}
runtime: import
source: builtin
---

# test-tool

This is the body text describing the tool.
"""


class TestParseToolMd:
    def test_parse_valid_tool_md(self):
        path = Path("/fake/tool.md")
        # We need to temporarily write the file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(SAMPLE_TOOL_MD)
            tmp_path = Path(f.name)

        try:
            tool = parse_tool_md(tmp_path)
            assert tool.name == "test-tool"
            assert tool.version == "1.0"
            assert tool.description == "A test tool"
            assert tool.objects == ["file", "database"]
            assert len(tool.capabilities) == 2
            assert tool.capabilities[0].name == "do_thing"
            assert tool.capabilities[0].danger_level == "medium"
            assert tool.capabilities[1].name == "do_other"
            assert tool.runtime == "import"
            assert tool.source == "builtin"
            assert "body text" in tool.body
        finally:
            tmp_path.unlink()

    def test_parse_no_frontmatter(self):
        import pytest
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Just a heading\nNo frontmatter here.")
            tmp_path = Path(f.name)
        try:
            with pytest.raises(ValueError, match="No YAML frontmatter"):
                parse_tool_md(tmp_path)
        finally:
            tmp_path.unlink()


class TestSplitFrontmatter:
    def test_split(self):
        frontmatter, body = _split_frontmatter(SAMPLE_TOOL_MD)
        assert "name: test-tool" in frontmatter
        assert "# test-tool" in body

    def test_no_frontmatter(self):
        frontmatter, body = _split_frontmatter("No frontmatter")
        assert frontmatter == ""
        assert body == "No frontmatter"


class TestGenerateToolMd:
    def test_roundtrip(self):
        tool_def = ToolDefinition(
            name="roundtrip",
            version="2.0",
            description="Roundtrip test",
            objects=["file"],
            capabilities=[
                Capability(name="cap1", description="First capability"),
                Capability(name="cap2", description="Second capability"),
            ],
            runtime="import",
            source="builtin",
            body="Test body",
        )
        md = generate_tool_md(tool_def)
        assert "name: roundtrip" in md
        assert "version: '2.0'" in md or 'version: "2.0"' in md
        assert "cap1" in md
        assert "cap2" in md
        assert "Test body" in md
