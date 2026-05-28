"""Tests for memory.py — unified SQLite memory store."""

import pytest

from therain2020.memory import Episode, Memory, SemanticEntry


@pytest.fixture
def mem():
    m = Memory(":memory:")
    yield m
    m.close()


class TestEpisodic:
    def test_log_and_retrieve(self, mem):
        eid = mem.log_episode(Episode(
            task="read file x",
            result="success",
            steps=2,
            tools=["read_file"],
            success=True,
        ))
        assert eid
        recent = mem.get_recent(10)
        assert len(recent) == 1
        assert recent[0].task == "read file x"
        assert recent[0].tools == ["read_file"]

    def test_get_recent_limit(self, mem):
        for i in range(5):
            mem.log_episode(Episode(task=f"task {i}", result="ok", success=True))
        assert len(mem.get_recent(3)) == 3
        assert len(mem.get_recent(10)) == 5

    def test_failure_tracking(self, mem):
        mem.log_episode(Episode(task="bad task", success=False, error="oops"))
        stats = mem.stats()
        assert stats["total_episodes"] == 1
        assert stats["successes"] == 0
        assert stats["failures"] == 1


class TestSemantic:
    def test_upsert_and_search(self, mem):
        mem.upsert_semantic(SemanticEntry(
            type="pattern",
            content="Always prefer read_file over cat for file access",
            confidence=0.9,
        ))
        results = mem.search_semantic("read_file cat")
        assert len(results) == 1
        assert results[0].type == "pattern"

    def test_search_fallback_like(self, mem):
        mem.upsert_semantic(SemanticEntry(
            type="fact",
            content="The codebase uses Python 3.11+",
        ))
        # Use a query without FTS5 operators to test LIKE fallback
        results = mem.search_semantic("codebase")
        assert len(results) >= 1

    def test_get_by_type(self, mem):
        mem.upsert_semantic(SemanticEntry(type="preference", content="use short names"))
        mem.upsert_semantic(SemanticEntry(type="fact", content="Python version is 3.12"))
        prefs = mem.get_semantic_by_type("preference")
        assert len(prefs) == 1
        facts = mem.get_semantic_by_type("fact")
        assert len(facts) == 1

    def test_consolidate(self, mem):
        eid = mem.log_episode(Episode(task="test task", success=True))
        mem.consolidate(
            [eid],
            SemanticEntry(type="pattern", content="discovered pattern", source_episodes=[eid]),
        )
        results = mem.search_semantic("pattern")
        assert len(results) == 1
        assert eid in results[0].source_episodes


class TestStats:
    def test_empty_stats(self, mem):
        stats = mem.stats()
        assert stats["total_episodes"] == 0
        assert stats["semantic_entries"] == 0
