"""Memory system with SQLite WAL backend. Phase 2.

Episodic: task execution records.
Semantic: distilled knowledge (preferences, facts, patterns).
FTS5 full-text search for fast retrieval.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog

from .memory_migrations import MigrationManager

logger = structlog.get_logger()

# ——— Data classes ———


@dataclass
class EpisodeEntry:
    """A single task execution record."""
    task_id: str
    task_type: str  # "goal" | "todo"
    task_summary: str
    tools_used: list[str] = field(default_factory=list)
    steps: int = 0
    success: bool = False
    error: str = ""
    non_set_changes: list[dict] = field(default_factory=list)
    timestamp: str = ""
    objects_before: dict = field(default_factory=dict)
    objects_after: dict = field(default_factory=dict)
    object_changes: list[dict] = field(default_factory=list)


@dataclass
class SemanticEntry:
    """A distilled knowledge entry."""
    id: str
    type: str  # "preference" | "fact" | "pattern"
    content: str
    confidence: float
    source_episodes: list[str] = field(default_factory=list)
    created_at: str = ""
    last_verified_at: str = ""
    reference_count: int = 0


# ——— SQLite backend ———


class MemoryStore:
    """SQLite-based memory backend with WAL mode. 类比: ext4 journal."""

    def __init__(self, db_path: str = "memory/agent.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-8000")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    def _migrate(self) -> None:
        """Apply versioned schema migrations."""
        mgr = MigrationManager(self.conn)
        applied = mgr.migrate()
        if applied:
            logger.info("schema_migrations_applied", versions=applied)

    def close(self):
        self.conn.close()

    # ——— Episodic ———

    def log_episode(self, entry: EpisodeEntry) -> None:
        entry.timestamp = entry.timestamp or datetime.now(UTC).isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO episodic
               (id, timestamp, task_type, task_summary, tools_used,
                steps, success, error, non_set_changes,
                objects_before, objects_after, object_changes, consolidated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (entry.task_id, entry.timestamp, entry.task_type,
             entry.task_summary, json.dumps(entry.tools_used),
             entry.steps, int(entry.success), entry.error,
             json.dumps(entry.non_set_changes),
             json.dumps(entry.objects_before, ensure_ascii=False),
             json.dumps(entry.objects_after, ensure_ascii=False),
             json.dumps(entry.object_changes, ensure_ascii=False)),
        )
        self.conn.commit()
        logger.info("episode_logged", task_id=entry.task_id)

    def get_recent(self, count: int = 10) -> list[EpisodeEntry]:
        rows = self.conn.execute(
            "SELECT * FROM episodic ORDER BY timestamp DESC LIMIT ?",
            (count,),
        ).fetchall()
        return [self._row_to_episode(r) for r in rows]

    def get_unconsolidated(self) -> list[EpisodeEntry]:
        rows = self.conn.execute(
            "SELECT * FROM episodic WHERE consolidated = 0 ORDER BY timestamp"
        ).fetchall()
        return [self._row_to_episode(r) for r in rows]

    def mark_consolidated(self, episode_ids: list[str]) -> None:
        self.conn.executemany(
            "UPDATE episodic SET consolidated = 1 WHERE id = ?",
            [(eid,) for eid in episode_ids],
        )
        self.conn.commit()

    def stats(self) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) as total, AVG(steps) as avg_steps, "
            "SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count "
            "FROM episodic"
        ).fetchone()
        total = row["total"]
        return {
            "total_episodes": total,
            "success_rate": round(row["success_count"] / total * 100, 1) if total else 0,
            "avg_steps": round(row["avg_steps"], 1) if row["avg_steps"] else 0,
        }

    def get_object_history(self, uri: str, limit: int = 10) -> list[dict]:
        """Query state change history for a specific object across episodes."""
        rows = self.conn.execute(
            """SELECT id, timestamp, task_type, task_summary, success,
                      objects_before, objects_after, object_changes
               FROM episodic
               WHERE objects_before LIKE ? OR objects_after LIKE ?
                  OR object_changes LIKE ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (f"%{uri}%", f"%{uri}%", f"%{uri}%", limit),
        ).fetchall()
        history = []
        for row in rows:
            changes = json.loads(row["object_changes"] or "[]")
            obj_changes = [c for c in changes if c.get("uri") == uri]
            history.append({
                "task_id": row["id"],
                "timestamp": row["timestamp"],
                "task_type": row["task_type"],
                "task_summary": row["task_summary"],
                "success": bool(row["success"]),
                "changes": obj_changes,
            })
        return history

    def get_non_set_history(self, limit: int = 20) -> list[dict]:
        """Query all dont-do rule change history."""
        rows = self.conn.execute(
            """SELECT id, timestamp, task_type, non_set_changes
               FROM episodic
               WHERE non_set_changes != '[]' AND non_set_changes != 'null'
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        history = []
        for row in rows:
            changes = json.loads(row["non_set_changes"] or "[]")
            for change in changes:
                change["task_id"] = row["id"]
                change["task_type"] = row["task_type"]
                history.append(change)
        return history

    # ——— Semantic ———

    def upsert_semantic(self, entry: SemanticEntry) -> None:
        entry.created_at = entry.created_at or datetime.now(UTC).isoformat()
        self.conn.execute(
            """INSERT INTO semantic
               (id, type, content, confidence, source_episodes,
                created_at, last_verified_at, reference_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               content=excluded.content,
               confidence=excluded.confidence,
               source_episodes=excluded.source_episodes,
               last_verified_at=excluded.last_verified_at,
               reference_count=reference_count + 1""",
            (entry.id, entry.type, entry.content, entry.confidence,
             json.dumps(entry.source_episodes), entry.created_at,
             entry.last_verified_at, entry.reference_count),
        )
        self.conn.commit()

    def search_semantic(self, keyword: str, limit: int = 10) -> list[SemanticEntry]:
        rows = self.conn.execute(
            "SELECT s.* FROM semantic s "
            "INNER JOIN semantic_fts f ON s.rowid = f.rowid "
            "WHERE semantic_fts MATCH ? "
            "ORDER BY s.confidence DESC, s.reference_count DESC "
            "LIMIT ?",
            (keyword, limit),
        ).fetchall()

        if not rows:
            rows = self.conn.execute(
                "SELECT * FROM semantic WHERE content LIKE ? "
                "ORDER BY confidence DESC LIMIT ?",
                (f"%{keyword}%", limit),
            ).fetchall()

        return [self._row_to_semantic(r) for r in rows]

    def list_semantic(self, entry_type: str = "", min_confidence: float = 0.0) -> list[SemanticEntry]:
        where = []
        params = []
        if entry_type:
            where.append("type = ?")
            params.append(entry_type)
        if min_confidence:
            where.append("confidence >= ?")
            params.append(min_confidence)
        query = "SELECT * FROM semantic"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY confidence DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_semantic(r) for r in rows]

    def delete_low_confidence(self, threshold: float = 0.3) -> int:
        cur = self.conn.execute(
            "DELETE FROM semantic WHERE confidence < ?", (threshold,)
        )
        self.conn.commit()
        return cur.rowcount

    def semantic_stats(self) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) as total, AVG(confidence) as avg_confidence, "
            "type FROM semantic GROUP BY type"
        ).fetchone()
        total_row = self.conn.execute("SELECT COUNT(*) FROM semantic").fetchone()
        return {
            "total": total_row[0],
            "by_type": {"avg_confidence": round(row["avg_confidence"], 2)} if row else {},
        }

    # ——— Helpers ———

    def _row_to_episode(self, row) -> EpisodeEntry:
        return EpisodeEntry(
            task_id=row["id"],
            task_type=row["task_type"],
            task_summary=row["task_summary"],
            tools_used=json.loads(row["tools_used"]),
            steps=row["steps"],
            success=bool(row["success"]),
            error=row["error"],
            non_set_changes=json.loads(row["non_set_changes"]),
            timestamp=row["timestamp"],
            objects_before=self._safe_json_load(row["objects_before"], {}),
            objects_after=self._safe_json_load(row["objects_after"], {}),
            object_changes=self._safe_json_load(row["object_changes"], []),
        )

    @staticmethod
    def _safe_json_load(value, default):
        try:
            return json.loads(value) if value else default
        except (json.JSONDecodeError, TypeError):
            return default

    def _row_to_semantic(self, row) -> SemanticEntry:
        return SemanticEntry(
            id=row["id"],
            type=row["type"],
            content=row["content"],
            confidence=row["confidence"],
            source_episodes=json.loads(row["source_episodes"]),
            created_at=row["created_at"],
            last_verified_at=row["last_verified_at"],
            reference_count=row["reference_count"],
        )


# ——— Backward-compatible wrapper ———


class EpisodicMemory:
    """Backward-compatible wrapper. 委托给 MemoryStore."""

    def __init__(self, db_path: str = "memory/agent.db"):
        self._store = MemoryStore(db_path)

    def log_episode(self, entry: EpisodeEntry) -> None:
        self._store.log_episode(entry)

    def get_recent(self, count: int = 10) -> list[EpisodeEntry]:
        return self._store.get_recent(count)

    def stats(self) -> dict:
        return self._store.stats()

    @property
    def store(self) -> MemoryStore:
        return self._store
