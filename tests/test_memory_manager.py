"""Tests for memory_manager.py — Claude Code-style MEMORY.md."""

from therain2020.memory_manager import MemoryManager


def test_ensure_creates_dirs(tmp_path):
    mgr = MemoryManager(base_dir=tmp_path)
    mgr.ensure()
    assert (tmp_path / "memory" / "MEMORY.md").exists()


def test_load_context_empty(tmp_path):
    mgr = MemoryManager(base_dir=tmp_path)
    mgr.ensure()
    ctx = mgr.load_context()
    assert "# Agent Memory" in ctx


def test_record_tool_updates_index(tmp_path):
    mgr = MemoryManager(base_dir=tmp_path)
    mgr.record_tool("image-convert", "Convert images", "from PIL import Image")
    ctx = mgr.load_context()
    assert "image-convert" in ctx
    assert "Convert images" in ctx


def test_record_session(tmp_path):
    mgr = MemoryManager(base_dir=tmp_path)
    mgr.record_session("test task", True, 3, ["read", "write"], 1.5)
    ctx = mgr.load_context()
    assert "test task" in ctx
    assert "read, write" in ctx


def test_record_learning(tmp_path):
    mgr = MemoryManager(base_dir=tmp_path)
    mgr.record_learning("error", "Never delete system files", "test task")
    ctx = mgr.load_context()
    assert "Never delete system files" in ctx


def test_index_has_entry(tmp_path):
    mgr = MemoryManager(base_dir=tmp_path)
    mgr.record_tool("foo", "desc")
    index = (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert "[Created Tools](tools.md)" in index
