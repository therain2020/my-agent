"""Event Store — append-only event log with snapshot support.

SQLite-backed, WAL mode. Each event is an immutable row in the event_log table.
The EventPublisher provides in-process synchronous pub/sub (NOT EDA Broker —
no persistence, no async, no external dependencies).

Snapshot: periodic state snapshots to avoid full replay for long histories.
"""

import json
import sqlite3
from datetime import UTC, datetime

import structlog

from .events import SAFETY_CRITICAL_EVENTS, AgentEvent, EventType

logger = structlog.get_logger()

SNAPSHOT_INTERVAL = 50  # Take a snapshot every N events per task


class EventPublisher:
    """In-process synchronous event notification.

    NOT an EDA Broker. Subscribers are called synchronously in the same thread.
    No persistence, no async, no network — per eda-tradeoffs.md:
    "simple system → direct call."
    """

    def __init__(self):
        self._subscribers: dict[str, list[callable]] = {}

    def subscribe(self, event_type: str, handler: callable) -> None:
        """Register a handler for a specific event type."""
        self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event: AgentEvent) -> None:
        """Notify all subscribers synchronously."""
        handlers = self._subscribers.get(event.event_type.value, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.error("event_handler_error",
                             event_type=event.event_type.value,
                             handler=str(handler), exc_info=True)


class EventStore:
    """SQLite append-only event log with snapshot support.

    Schema:
        event_log(id, event_type, timestamp, task_id, payload)
        snapshots(task_id, event_id, state_json, taken_at)
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.publisher = EventPublisher()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                task_id TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_event_task ON event_log(task_id);
            CREATE INDEX IF NOT EXISTS idx_event_type ON event_log(event_type);

            CREATE TABLE IF NOT EXISTS snapshots (
                task_id TEXT PRIMARY KEY,
                last_event_id INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                taken_at TEXT NOT NULL
            );
        """)
        self.conn.commit()

    # ——— Write ———

    def append(self, event: AgentEvent) -> int:
        """Append an event to the log. Returns the event ID.

        Safety-critical events trigger synchronous subscriber notification
        before returning. Observation events notify after appending.
        """
        cursor = self.conn.execute(
            "INSERT INTO event_log (event_type, timestamp, task_id, payload) "
            "VALUES (?, ?, ?, ?)",
            (event.event_type.value, event.timestamp, event.task_id,
             json.dumps(event.payload, ensure_ascii=False)),
        )
        self.conn.commit()
        event_id = cursor.lastrowid

        # Safety-critical: notify synchronously before returning
        if event.event_type in SAFETY_CRITICAL_EVENTS:
            self.publisher.publish(event)

        return event_id

    def append_and_notify(self, event: AgentEvent) -> int:
        """Append + notify subscribers (for observation events)."""
        event_id = self.append(event)
        if event.event_type not in SAFETY_CRITICAL_EVENTS:
            self.publisher.publish(event)
        return event_id

    # ——— Read: Replay ———

    def replay_task(self, task_id: str) -> list[AgentEvent]:
        """Replay all events for a single task, ordered by insertion."""
        rows = self.conn.execute(
            "SELECT event_type, timestamp, task_id, payload "
            "FROM event_log WHERE task_id = ? ORDER BY id",
            (task_id,),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def replay_all(self, limit: int = 500) -> list[AgentEvent]:
        """Replay recent events across all tasks."""
        rows = self.conn.execute(
            "SELECT event_type, timestamp, task_id, payload "
            "FROM event_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_event(r) for r in reversed(rows)]

    # ——— Read: Query ———

    def get_events_by_type(self, event_type: EventType,
                           limit: int = 100) -> list[AgentEvent]:
        rows = self.conn.execute(
            "SELECT event_type, timestamp, task_id, payload "
            "FROM event_log WHERE event_type = ? "
            "ORDER BY id DESC LIMIT ?",
            (event_type.value, limit),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def count_events_for_task(self, task_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM event_log WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ——— Snapshot ———

    def maybe_snapshot(self, task_id: str) -> None:
        """Take a snapshot if enough events have accumulated."""
        count = self.count_events_for_task(task_id)
        if count > 0 and count % SNAPSHOT_INTERVAL == 0:
            last_id = self.conn.execute(
                "SELECT MAX(id) as max_id FROM event_log WHERE task_id = ?",
                (task_id,),
            ).fetchone()["max_id"]
            state = self._build_state_from_events(task_id)
            self.conn.execute(
                "INSERT OR REPLACE INTO snapshots "
                "(task_id, last_event_id, state_json, taken_at) "
                "VALUES (?, ?, ?, ?)",
                (task_id, last_id,
                 json.dumps(state, ensure_ascii=False),
                 datetime.now(UTC).isoformat()),
            )
            self.conn.commit()
            logger.info("snapshot_taken", task_id=task_id, event_count=count)

    def get_latest_snapshot(self, task_id: str) -> dict | None:
        """Get the latest snapshot for a task, or None."""
        row = self.conn.execute(
            "SELECT state_json, last_event_id FROM snapshots "
            "WHERE task_id = ? ORDER BY taken_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if row:
            return {
                "state": json.loads(row["state_json"]),
                "last_event_id": row["last_event_id"],
            }
        return None

    def _build_state_from_events(self, task_id: str) -> dict:
        """Build current state by replaying events (used for snapshots)."""
        events = self.replay_task(task_id)
        state = {
            "objects": {},
            "tools_called": [],
            "corrections": [],
            "rules_added": [],
            "steps": 0,
        }
        for e in events:
            if e.event_type == EventType.OBJECT_OBSERVED:
                state["objects"][e.payload["uri"]] = e.payload
            elif e.event_type == EventType.TOOL_CALLED:
                state["tools_called"].append(e.payload)
                state["steps"] += 1
            elif e.event_type == EventType.CORRECTION_APPLIED:
                state["corrections"].append(e.payload)
            elif e.event_type == EventType.RULE_ADDED:
                state["rules_added"].append(e.payload)
        return state

    # ——— Helpers ———

    def _row_to_event(self, row) -> AgentEvent:
        return AgentEvent(
            event_type=EventType(row["event_type"]),
            task_id=row["task_id"],
            timestamp=row["timestamp"],
            payload=json.loads(row["payload"]),
        )

    def stats(self) -> dict:
        """Event store statistics."""
        total = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM event_log"
        ).fetchone()["cnt"]
        by_type = {}
        for row in self.conn.execute(
            "SELECT event_type, COUNT(*) as cnt "
            "FROM event_log GROUP BY event_type"
        ).fetchall():
            by_type[row["event_type"]] = row["cnt"]
        return {"total_events": total, "by_type": by_type}
