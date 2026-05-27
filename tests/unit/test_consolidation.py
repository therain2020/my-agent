"""Tests for memory consolidation."""

import tempfile

from agent.consolidation import ConsolidationDaemon
from agent.memory import EpisodeEntry, MemoryStore, SemanticEntry


class TestConsolidationDaemon:
    def test_should_consolidate_threshold(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            daemon = ConsolidationDaemon(store)

            # Add 10 unconsolidated episodes
            for i in range(10):
                store.log_episode(EpisodeEntry(
                    task_id=f"t-{i:03d}", task_type="todo",
                    task_summary=f"task {i}", success=True,
                ))

            should, reason = daemon.should_consolidate()
            assert should is True
            assert "count_threshold" in reason
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_should_not_consolidate_few(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            daemon = ConsolidationDaemon(store)

            for i in range(2):
                store.log_episode(EpisodeEntry(
                    task_id=f"t-{i:03d}", task_type="todo",
                    task_summary=f"task {i}", success=True,
                ))

            should, reason = daemon.should_consolidate()
            assert should is False
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_manual_always_runs(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            daemon = ConsolidationDaemon(store)
            should, reason = daemon.should_consolidate(manual=True)
            assert should is True
            assert reason == "manual"
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_rule_based_extraction(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            daemon = ConsolidationDaemon(store)

            for i in range(5):
                store.log_episode(EpisodeEntry(
                    task_id=f"t-{i:03d}", task_type="todo",
                    task_summary=f"task {i}",
                    tools_used=["file-system.read_file", "git.commit"],
                    success=True,
                ))

            episodes = store.get_unconsolidated()
            entries = daemon._rule_based_extract(episodes)
            # file-system and git used in all 5 (>60%) → should extract
            assert len(entries) >= 1
            tool_names = [e.id for e in entries]
            assert any("file-system" in t for t in tool_names)
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_find_similar(self):
        d = tempfile.mkdtemp()
        try:
            store = MemoryStore(db_path=f"{d}/test.db")
            store.upsert_semantic(SemanticEntry(
                id="sem-exist", type="preference",
                content="User prefers pytest for testing",
                confidence=0.8,
            ))
            daemon = ConsolidationDaemon(store)

            similar = daemon._find_similar(SemanticEntry(
                id="new", type="preference",
                content="User uses pytest for testing",
                confidence=0.7,
            ))
            assert similar is not None
            assert similar.id == "sem-exist"

            different = daemon._find_similar(SemanticEntry(
                id="new2", type="preference",
                content="Project uses PostgreSQL database",
                confidence=0.7,
            ))
            assert different is None
            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
