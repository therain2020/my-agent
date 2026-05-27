"""Tests for episodic memory."""

import tempfile

from agent.memory import EpisodeEntry, EpisodicMemory


class TestEpisodicMemory:
    def test_log_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = EpisodicMemory(base_path=tmp)
            entry = EpisodeEntry(
                task_id="t-001",
                task_type="todo",
                task_summary="Test task",
                tools_used=["file-system.read_file"],
                steps=2,
                success=True,
            )
            log_path = mem.log_episode(entry)
            assert log_path.exists()
            content = log_path.read_text(encoding="utf-8")
            assert "t-001" in content or "Test task" in content

    def test_log_failed_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = EpisodicMemory(base_path=tmp)
            entry = EpisodeEntry(
                task_id="t-002",
                task_type="goal",
                task_summary="Failed task",
                tools_used=[],
                steps=1,
                success=False,
                error="Something went wrong",
            )
            mem.log_episode(entry)
            entries = mem.get_recent(10)
            assert len(entries) >= 1
            found = [e for e in entries if e.task_type == "goal"]
            assert len(found) >= 1
            assert found[0].success is False
            assert "Something went wrong" in found[0].error

    def test_get_recent_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = EpisodicMemory(base_path=tmp)
            entries = mem.get_recent(10)
            assert entries == []

    def test_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = EpisodicMemory(base_path=tmp)
            mem.log_episode(EpisodeEntry(
                task_id="t-010", task_type="todo",
                task_summary="ok", tools_used=["a"], steps=1, success=True,
            ))
            mem.log_episode(EpisodeEntry(
                task_id="t-011", task_type="todo",
                task_summary="fail", tools_used=["b"], steps=3, success=False,
            ))
            stats = mem.stats()
            assert stats["total_episodes"] >= 2
            assert 0 <= stats["success_rate"] <= 100
