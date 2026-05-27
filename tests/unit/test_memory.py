"""Tests for SQLite-backed memory."""

import tempfile

from agent.memory import EpisodeEntry, EpisodicMemory, MemoryStore, SemanticEntry


class TestMemoryStore:
    def test_log_and_retrieve_episode(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            store.log_episode(EpisodeEntry(
                task_id="t-001", task_type="todo",
                task_summary="Test task",
                tools_used=["file-system.read_file"],
                steps=2, success=True,
            ))
            recent = store.get_recent(10)
            assert len(recent) == 1
            assert recent[0].task_summary == "Test task"
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_get_recent_empty(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            assert store.get_recent(10) == []
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_stats(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            store.log_episode(EpisodeEntry(
                task_id="t-010", task_type="todo",
                task_summary="ok", tools_used=["a"], steps=1, success=True,
            ))
            store.log_episode(EpisodeEntry(
                task_id="t-011", task_type="todo",
                task_summary="fail", tools_used=["b"], steps=3, success=False,
            ))
            stats = store.stats()
            assert stats["total_episodes"] >= 2
            assert 0 <= stats["success_rate"] <= 100
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_unconsolidated(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            store.log_episode(EpisodeEntry(
                task_id="t-020", task_type="todo", task_summary="x",
            ))
            unconsolidated = store.get_unconsolidated()
            assert len(unconsolidated) == 1
            store.mark_consolidated(["t-020"])
            assert store.get_unconsolidated() == []
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_semantic_upsert_and_search(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            store.upsert_semantic(SemanticEntry(
                id="s-001", type="preference",
                content="User prefers pytest over unittest",
                confidence=0.9,
            ))
            store.upsert_semantic(SemanticEntry(
                id="s-002", type="fact",
                content="Database is PostgreSQL 15",
                confidence=0.8,
            ))
            results = store.search_semantic("pytest")
            assert len(results) == 1
            assert "pytest" in results[0].content
            results2 = store.search_semantic("PostgreSQL")
            assert len(results2) == 1
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_semantic_fallback_search(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            store.upsert_semantic(SemanticEntry(
                id="s-003", type="fact", content="Project uses FastAPI",
                confidence=0.7,
            ))
            results = store.search_semantic("Fast")
            assert len(results) >= 1
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_semantic_list_by_type(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            store.upsert_semantic(SemanticEntry(
                id="p-1", type="preference", content="A", confidence=0.9,
            ))
            store.upsert_semantic(SemanticEntry(
                id="f-1", type="fact", content="B", confidence=0.8,
            ))
            prefs = store.list_semantic(entry_type="preference")
            assert len(prefs) == 1
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_delete_low_confidence(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            store.upsert_semantic(SemanticEntry(
                id="low-1", type="fact", content="Uncertain", confidence=0.2,
            ))
            store.upsert_semantic(SemanticEntry(
                id="high-1", type="fact", content="Certain", confidence=0.9,
            ))
            deleted = store.delete_low_confidence(0.3)
            assert deleted == 1
            remaining = store.list_semantic()
            assert len(remaining) == 1
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class TestEpisodicMemoryWrapper:
    def test_backward_compat(self):
        d = tempfile.mkdtemp()
        try:
            mem = EpisodicMemory(db_path=f"{d}/agent.db")
            mem.log_episode(EpisodeEntry(
                task_id="t-100", task_type="todo",
                task_summary="Backward compat test", tools_used=["x"],
                steps=1, success=True,
            ))
            recent = mem.get_recent(5)
            assert len(recent) == 1
            mem.store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
