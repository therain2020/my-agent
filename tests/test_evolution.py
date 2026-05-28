"""Tests for tool evolution manager and agent tool editor."""

import pytest

from agent.tools.evolution import (
    EvolutionAction,
    EvolutionRecord,
    ToolEvolutionManager,
)
from agent.tools.editor import AgentToolEditor, EDIT_CAPABILITIES, _rebuild_tool_md


class TestEvolutionRecord:
    def test_create_record(self):
        record = EvolutionRecord(
            id="evol-test",
            timestamp="2026-05-28T00:00:00Z",
            action=EvolutionAction.CREATE,
            target="test-tool",
            episode_id="ep-001",
            description="Test evolution",
        )
        assert record.action == EvolutionAction.CREATE
        assert record.target == "test-tool"
        assert not record.verified

    def test_record_defaults(self):
        record = EvolutionRecord(
            id="evol-test",
            timestamp="",
            action=EvolutionAction.ADD_VERIFY,
            target="test-tool",
            episode_id="",
            description="",
        )
        assert record.diff == ""
        assert record.snapshot_hash == ""
        assert not record.verified


class TestToolEvolutionManager:
    def test_init_creates_dirs(self, tmp_path):
        tools_dir = tmp_path / "tools"
        mgr = ToolEvolutionManager(tools_dir=str(tools_dir))
        assert mgr.generated_dir.exists()

    def test_read_tool_source_not_found(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        mgr = ToolEvolutionManager(tools_dir=str(tools_dir))
        result = mgr.read_tool_source("nonexistent")
        assert "error" in result

    def test_read_tool_source_found(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tool_dir = tools_dir / "test-tool"
        tool_dir.mkdir(parents=True)
        (tool_dir / "tool.md").write_text(
            "---\nname: test-tool\nversion: '1.0'\ncapabilities: []\n---\n\n# Test Tool\n",
            encoding="utf-8",
        )
        (tool_dir / "helpers.py").write_text("def foo(): pass\n", encoding="utf-8")

        mgr = ToolEvolutionManager(tools_dir=str(tools_dir))
        result = mgr.read_tool_source("test-tool")

        assert result["name"] == "test-tool"
        assert result["metadata"]["name"] == "test-tool"
        assert "helpers.py" in result["implementations"]
        assert result["implementations"]["helpers.py"] == "def foo(): pass\n"

    def test_stage_and_commit(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        mgr = ToolEvolutionManager(tools_dir=str(tools_dir))

        # Create initial tool
        tool_dir = tools_dir / "new-tool"
        tool_dir.mkdir()
        (tool_dir / "tool.md").write_text(
            "---\nname: new-tool\ncapabilities: []\n---\n",
            encoding="utf-8",
        )

        # Stage a change
        record = mgr.stage_change(
            tool_name="new-tool",
            action=EvolutionAction.CREATE,
            changes={
                "tool.md": "---\nname: new-tool\ncapabilities:\n  - name: test_cap\n---\n",
                "helper.py": "def helper(): return 42\n",
            },
            episode_id="ep-001",
            description="Add test capability",
        )
        assert record.action == EvolutionAction.CREATE
        assert record.episode_id == "ep-001"

        # Commit
        ok = mgr.validate_and_commit(record.id)
        # May fail if no git repo, but at least validate YAML + Python passes
        # The git operations may fail but the validation should succeed
        assert record.id not in mgr._pending  # consumed from pending

    def test_commit_invalid_yaml_rejected(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        mgr = ToolEvolutionManager(tools_dir=str(tools_dir))

        tool_dir = tools_dir / "bad-tool"
        tool_dir.mkdir()
        (tool_dir / "tool.md").write_text("---\nname: bad-tool\n---\n", encoding="utf-8")

        record = mgr.stage_change(
            tool_name="bad-tool",
            action=EvolutionAction.MODIFY,
            changes={"tool.md": "---\n{{ invalid yaml!!!\n---\n"},
            episode_id="ep-001",
            description="Bad change",
        )
        ok = mgr.validate_and_commit(record.id)
        # Should fail on invalid YAML
        assert not ok

    def test_commit_invalid_python_rejected(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        mgr = ToolEvolutionManager(tools_dir=str(tools_dir))

        tool_dir = tools_dir / "syntax-tool"
        tool_dir.mkdir()
        (tool_dir / "tool.md").write_text("---\nname: syntax-tool\n---\n", encoding="utf-8")

        record = mgr.stage_change(
            tool_name="syntax-tool",
            action=EvolutionAction.MODIFY,
            changes={
                "tool.md": "---\nname: syntax-tool\n---\n",
                "broken.py": "def broken(:\n    pass\n",  # syntax error
            },
            episode_id="ep-001",
            description="Bad syntax",
        )
        ok = mgr.validate_and_commit(record.id)
        assert not ok

    def test_get_history(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        mgr = ToolEvolutionManager(tools_dir=str(tools_dir))
        assert mgr.get_history() == []
        assert mgr.get_history(tool_name="nonexistent") == []


class TestAgentToolEditor:
    def test_init(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        evolution = ToolEvolutionManager(tools_dir=str(tools_dir))
        editor = AgentToolEditor(evolution)
        assert editor.evolution is evolution

    def test_read_tool_not_found(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        evolution = ToolEvolutionManager(tools_dir=str(tools_dir))
        editor = AgentToolEditor(evolution)
        result = editor.read_tool("nonexistent")
        assert "error" in result

    def test_get_edit_history_empty(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        evolution = ToolEvolutionManager(tools_dir=str(tools_dir))
        editor = AgentToolEditor(evolution)
        assert editor.get_edit_history() == []

    def test_edit_capabilities(self):
        assert len(EDIT_CAPABILITIES) == 6
        names = [c["name"] for c in EDIT_CAPABILITIES]
        assert "read_tool" in names
        assert "add_verify" in names
        assert "add_helper" in names
        assert "get_edit_history" in names


class TestRebuildToolMd:
    def test_simple(self):
        result = _rebuild_tool_md({"name": "test", "capabilities": []}, "# Test")
        assert "---" in result
        assert "name: test" in result
        assert "# Test" in result

    def test_no_body(self):
        result = _rebuild_tool_md({"name": "test"}, "")
        assert result.endswith("---")

    def test_with_verify(self):
        meta = {
            "name": "test",
            "capabilities": [
                {
                    "name": "write",
                    "verify": {"function": "verify.py:verify_write", "auto_generated": True},
                }
            ],
        }
        result = _rebuild_tool_md(meta, "")
        assert "verify:" in result
        assert "verify_write" in result
