"""Unified SQLite memory store.

Single-store design — the episodic table IS the event log.
Replaces the old dual-store (MemoryStore + EventStore) with one
source of truth.

Migrated from agent/memory.py MemoryStore (SQL schema, FTS5, WAL mode).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .constants import RECENT_EPISODES_LIMIT, SEMANTIC_SEARCH_LIMIT


@dataclass
class Episode:
    task: str
    result: str = ""
    steps: int = 1
    tools: list[str] = field(default_factory=list)
    success: bool = False
    error: str = ""
    task_type: str = ""
    id: str = ""
    timestamp: str = ""


@dataclass
class SemanticEntry:
    type: str  # "preference" | "fact" | "pattern"
    content: str
    confidence: float = 0.5
    source_episodes: list[str] = field(default_factory=list)
    id: str = ""
    created_at: str = ""
    reference_count: int = 0


class Memory:
    """Unified SQLite store with WAL mode and FTS5 semantic search."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS episodic (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                task TEXT NOT NULL,
                task_type TEXT DEFAULT '',
                result TEXT DEFAULT '',
                steps INTEGER DEFAULT 1,
                tools TEXT DEFAULT '[]',
                success INTEGER DEFAULT 0,
                error TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS semantic (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                source_episodes TEXT DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                reference_count INTEGER DEFAULT 0
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS semantic_fts
                USING fts5(content, content=semantic, content_rowid='rowid');
            CREATE TRIGGER IF NOT EXISTS semantic_ai AFTER INSERT ON semantic BEGIN
                INSERT INTO semantic_fts(rowid, content) VALUES (new.rowid, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS semantic_ad AFTER DELETE ON semantic BEGIN
                INSERT INTO semantic_fts(semantic_fts, rowid, content)
                    VALUES('delete', old.rowid, old.content);
            END;
            CREATE TRIGGER IF NOT EXISTS semantic_au AFTER UPDATE ON semantic BEGIN
                INSERT INTO semantic_fts(semantic_fts, rowid, content)
                    VALUES('delete', old.rowid, old.content);
                INSERT INTO semantic_fts(rowid, content)
                    VALUES (new.rowid, new.content);
            END;
        """)

    # -- episodic ---------------------------------------------------------

    def log_episode(self, episode: Episode) -> str:
        eid = episode.id or uuid.uuid4().hex[:12]
        ts = episode.timestamp or time.strftime("%Y-%m-%dT%H:%M:%S")
        self.db.execute(
            """INSERT OR REPLACE INTO episodic
               (id, timestamp, task, task_type, result, steps, tools, success, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid, ts, episode.task, episode.task_type, episode.result,
                episode.steps, json.dumps(episode.tools),
                1 if episode.success else 0, episode.error,
            ),
        )
        self.db.commit()
        return eid

    def get_recent(self, limit: int = RECENT_EPISODES_LIMIT) -> list[Episode]:
        rows = self.db.execute(
            "SELECT * FROM episodic ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_episode(r) for r in rows]

    def get_unconsolidated(self) -> list[Episode]:
        rows = self.db.execute(
            "SELECT * FROM episodic WHERE id NOT IN "
            "(SELECT json_each.value FROM semantic, json_each(semantic.source_episodes))"
        ).fetchall()
        return [_row_to_episode(r) for r in rows]

    def mark_consolidated(self, episode_ids: list[str]):
        pass  # handled implicitly via source_episodes in semantic entries

    # -- semantic ---------------------------------------------------------

    def search_semantic(self, query: str, limit: int = SEMANTIC_SEARCH_LIMIT) -> list[SemanticEntry]:
        try:
            rows = self.db.execute(
                """SELECT s.* FROM semantic s
                   JOIN semantic_fts fts ON s.rowid = fts.rowid
                   WHERE semantic_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # FTS5 query syntax error — fall back to LIKE
            rows = self.db.execute(
                "SELECT * FROM semantic WHERE content LIKE ? LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        return [_row_to_semantic(r) for r in rows]

    def upsert_semantic(self, entry: SemanticEntry) -> str:
        sid = entry.id or uuid.uuid4().hex[:12]
        ts = entry.created_at or time.strftime("%Y-%m-%dT%H:%M:%S")
        self.db.execute(
            """INSERT OR REPLACE INTO semantic
               (id, type, content, confidence, source_episodes, created_at, reference_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                sid, entry.type, entry.content, entry.confidence,
                json.dumps(entry.source_episodes), ts, entry.reference_count,
            ),
        )
        self.db.commit()
        return sid

    def get_semantic_by_type(self, stype: str) -> list[SemanticEntry]:
        rows = self.db.execute(
            "SELECT * FROM semantic WHERE type = ? ORDER BY confidence DESC",
            (stype,),
        ).fetchall()
        return [_row_to_semantic(r) for r in rows]

    def consolidate(self, episode_ids: list[str], new_semantic: SemanticEntry) -> str:
        """Persist extracted knowledge and link source episodes."""
        sid = self.upsert_semantic(new_semantic)
        # bump reference counts on existing matching entries
        for eid in episode_ids:
            self.db.execute(
                "UPDATE semantic SET reference_count = reference_count + 1 "
                "WHERE source_episodes LIKE ?",
                (f"%{eid}%",),
            )
        self.db.commit()
        return sid

    # -- stats ------------------------------------------------------------

    def stats(self) -> dict:
        total = self.db.execute("SELECT COUNT(*) FROM episodic").fetchone()[0]
        successes = self.db.execute(
            "SELECT COUNT(*) FROM episodic WHERE success = 1"
        ).fetchone()[0]
        semantic_count = self.db.execute(
            "SELECT COUNT(*) FROM semantic"
        ).fetchone()[0]
        return {
            "total_episodes": total,
            "successes": successes,
            "failures": total - successes,
            "semantic_entries": semantic_count,
        }

    def close(self):
        self.db.close()


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        timestamp=row["timestamp"],
        task=row["task"],
        task_type=row["task_type"],
        result=row["result"],
        steps=row["steps"],
        tools=json.loads(row["tools"]),
        success=bool(row["success"]),
        error=row["error"],
    )


def _row_to_semantic(row: sqlite3.Row) -> SemanticEntry:
    return SemanticEntry(
        id=row["id"],
        type=row["type"],
        content=row["content"],
        confidence=row["confidence"],
        source_episodes=json.loads(row["source_episodes"]),
        created_at=row["created_at"],
        reference_count=row["reference_count"],
    )
