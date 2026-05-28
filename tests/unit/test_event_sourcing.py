"""Tests for Event Sourcing memory system.

Covers:
- Event creation with factory helpers
- EventStore append + replay
- Snapshot creation and replay
- EventPublisher in-process pub/sub
- Consistency model: safety-critical events synchronous
- Migration 003 creates event_log table
"""

import tempfile

import pytest

from agent.event_store import EventPublisher, EventStore
from agent.events import (
    SAFETY_CRITICAL_EVENTS,
    EventType,
    correction_applied,
    goal_completed,
    goal_started,
    goal_verified,
    object_observed,
    plan_generated,
    tool_called,
    tool_result,
)
from agent.memory import MemoryStore

# ——— Event Factory Helpers ———


class TestEventFactories:
    """All factory helpers produce valid AgentEvent instances."""

    def test_goal_started(self):
        e = goal_started("t-1", "Deploy to production")
        assert e.event_type == EventType.GOAL_STARTED
        assert e.payload["goal"] == "Deploy to production"

    def test_object_observed(self):
        e = object_observed("t-1", "file://main.py", "file", {"size": 100})
        assert e.event_type == EventType.OBJECT_OBSERVED
        assert e.payload["uri"] == "file://main.py"

    def test_plan_generated(self):
        steps = [{"action": "read", "verify": "manual"}]
        e = plan_generated("t-1", steps)
        assert e.event_type == EventType.PLAN_GENERATED
        assert e.payload["step_count"] == 1

    def test_tool_called_and_result(self):
        called = tool_called("t-1", "file-system", "read_file",
                             {"path": "main.py"})
        assert called.event_type == EventType.TOOL_CALLED
        result = tool_result("t-1", "file-system", "read_file",
                             "content here", success=True)
        assert result.event_type == EventType.TOOL_RESULT
        assert result.payload["success"] is True

    def test_correction_applied(self):
        e = correction_applied("t-1", "corr-1", "rule-1", "Don't do X")
        assert e.event_type == EventType.CORRECTION_APPLIED

    def test_rule_added_is_safety_critical(self):
        """Rule additions must be in the safety-critical set."""
        assert EventType.RULE_ADDED in SAFETY_CRITICAL_EVENTS

    def test_goal_verified_and_completed(self):
        v = goal_verified("t-1", True, 0.95, "All criteria met")
        assert v.payload["achieved"] is True
        c = goal_completed("t-1", True, 5, 12.3)
        assert c.payload["steps"] == 5

    def test_timestamp_auto_set(self):
        e = goal_started("t-1", "test")
        assert e.timestamp
        assert "T" in e.timestamp  # ISO format


# ——— Event Publisher ———


class TestEventPublisher:
    """In-process synchronous pub/sub (NOT EDA Broker)."""

    def test_subscribe_and_publish(self):
        received = []

        def handler(event):
            received.append(event)

        pub = EventPublisher()
        pub.subscribe("goal_started", handler)
        e = goal_started("t-1", "test")
        pub.publish(e)

        assert len(received) == 1
        assert received[0].task_id == "t-1"

    def test_multiple_subscribers(self):
        results = []

        def h1(e):
            results.append(("h1", e.task_id))

        def h2(e):
            results.append(("h2", e.task_id))

        pub = EventPublisher()
        pub.subscribe("tool_called", h1)
        pub.subscribe("tool_called", h2)
        pub.publish(tool_called("t-2", "fs", "read", {}))

        assert len(results) == 2

    def test_handler_error_does_not_crash(self):
        def bad_handler(event):
            raise ValueError("oops")

        pub = EventPublisher()
        pub.subscribe("goal_started", bad_handler)
        # Should not raise
        pub.publish(goal_started("t-1", "test"))


# ——— Event Store ———


class TestEventStore:
    """SQLite append-only event log."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        d = tempfile.mkdtemp()
        self._tmpdir = d
        self.store = MemoryStore(db_path=f"{d}/test.db")
        self.event_store = EventStore(self.store.conn)
        yield
        self.store.close()
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    def test_append_and_replay(self):
        self.event_store.append(goal_started("t-1", "Test goal"))
        self.event_store.append(object_observed(
            "t-1", "file://a.py", "file", {"size": 100},
        ))
        self.event_store.append(goal_completed("t-1", True, 1, 5.0))

        events = self.event_store.replay_task("t-1")
        assert len(events) == 3
        assert events[0].event_type == EventType.GOAL_STARTED
        assert events[1].event_type == EventType.OBJECT_OBSERVED
        assert events[2].event_type == EventType.GOAL_COMPLETED

    def test_replay_isolated_per_task(self):
        self.event_store.append(goal_started("t-a", "Task A"))
        self.event_store.append(goal_started("t-b", "Task B"))

        events_a = self.event_store.replay_task("t-a")
        assert len(events_a) == 1
        assert events_a[0].payload["goal"] == "Task A"

    def test_count_events(self):
        self.event_store.append(goal_started("t-1", "x"))
        self.event_store.append(tool_called("t-1", "fs", "read", {}))
        assert self.event_store.count_events_for_task("t-1") == 2

    def test_get_events_by_type(self):
        self.event_store.append(goal_started("t-1", "x"))
        self.event_store.append(tool_called("t-1", "fs", "read", {}))
        self.event_store.append(tool_result("t-1", "fs", "read", "ok"))

        tool_events = self.event_store.get_events_by_type(
            EventType.TOOL_CALLED, limit=10,
        )
        assert len(tool_events) == 1

    def test_full_task_flow_replay(self):
        """End-to-end: record a full goal lifecycle and replay."""
        tid = "t-full"
        self.event_store.append(goal_started(tid, "Full test"))
        self.event_store.append(object_observed(tid, "file://x", "file", {"v": 1}))
        self.event_store.append(plan_generated(tid, [{"action": "edit"}]))
        self.event_store.append(tool_called(tid, "fs", "write", {}))
        self.event_store.append(tool_result(tid, "fs", "write", "done"))
        self.event_store.append(goal_verified(tid, True, 0.9, "ok"))
        self.event_store.append(goal_completed(tid, True, 1, 3.0))

        events = self.event_store.replay_task(tid)
        assert len(events) == 7

        # Verify event ordering matches insertion order
        types = [e.event_type for e in events]
        expected = [
            EventType.GOAL_STARTED,
            EventType.OBJECT_OBSERVED,
            EventType.PLAN_GENERATED,
            EventType.TOOL_CALLED,
            EventType.TOOL_RESULT,
            EventType.GOAL_VERIFIED,
            EventType.GOAL_COMPLETED,
        ]
        assert types == expected

    def test_stats(self):
        self.event_store.append(goal_started("t-1", "x"))
        self.event_store.append(tool_called("t-1", "fs", "read", {}))
        stats = self.event_store.stats()
        assert stats["total_events"] == 2
        assert stats["by_type"]["goal_started"] == 1


# ——— Snapshot ———


class TestSnapshot:
    """Periodic state snapshots for replay efficiency."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        d = tempfile.mkdtemp()
        self._tmpdir = d
        self.store = MemoryStore(db_path=f"{d}/test.db")
        self.event_store = EventStore(self.store.conn)
        yield
        self.store.close()
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    def test_snapshot_taken_at_interval(self):
        """Snapshots should be created every SNAPSHOT_INTERVAL events."""
        tid = "t-snap"
        from agent.event_store import SNAPSHOT_INTERVAL

        # Add exactly SNAPSHOT_INTERVAL events
        for i in range(SNAPSHOT_INTERVAL):
            self.event_store.append(tool_called(tid, "fs", f"op{i}", {}))

        self.event_store.maybe_snapshot(tid)
        snap = self.event_store.get_latest_snapshot(tid)
        assert snap is not None
        assert "state" in snap
        assert snap["state"]["steps"] == SNAPSHOT_INTERVAL

    def test_no_snapshot_below_interval(self):
        tid = "t-nosnap"
        for i in range(10):
            self.event_store.append(tool_called(tid, "fs", f"op{i}", {}))

        self.event_store.maybe_snapshot(tid)
        snap = self.event_store.get_latest_snapshot(tid)
        # Should be None unless 10 happens to be a multiple of SNAPSHOT_INTERVAL
        from agent.event_store import SNAPSHOT_INTERVAL
        if 10 % SNAPSHOT_INTERVAL != 0:
            assert snap is None


# ——— Migration 003 ———


class TestMigration003:
    """Verify migration 003 creates event_log and snapshots tables."""

    def test_migration_003_creates_tables(self):
        import sqlite3
        d = tempfile.mkdtemp()
        try:
            db_path = f"{d}/test.db"
            # Create DB with old schema (no event tables)
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE IF NOT EXISTS episodic (id TEXT)")
            conn.commit()
            conn.close()

            # Open with MemoryStore — migration 003 should run
            store = MemoryStore(db_path=db_path)
            # Verify event_log table exists
            row = store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='event_log'"
            ).fetchone()
            assert row is not None, "Migration 003 should create event_log table"

            row = store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='snapshots'"
            ).fetchone()
            assert row is not None, "Migration 003 should create snapshots table"

            store.close()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
