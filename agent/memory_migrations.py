"""Versioned schema migrations for SQLite memory store.

Replaces the ad-hoc try/except pattern in MemoryStore._migrate_schema()
with tracked, versioned migrations. Each migration is idempotent and
recorded in the schema_version table.
"""

import sqlite3
from datetime import UTC, datetime

import structlog

logger = structlog.get_logger()

MIGRATIONS: list[tuple[str, str]] = [
    ("001_initial", """
        CREATE TABLE IF NOT EXISTS episodic (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            task_type TEXT NOT NULL,
            task_summary TEXT NOT NULL,
            tools_used TEXT DEFAULT '[]',
            steps INTEGER DEFAULT 0,
            success INTEGER DEFAULT 0,
            error TEXT DEFAULT '',
            non_set_changes TEXT DEFAULT '[]',
            objects_before TEXT DEFAULT '{}',
            objects_after TEXT DEFAULT '{}',
            object_changes TEXT DEFAULT '[]',
            consolidated INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS semantic (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK(type IN ('preference','fact','pattern')),
            content TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            source_episodes TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            last_verified_at TEXT,
            reference_count INTEGER DEFAULT 0
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS semantic_fts
            USING fts5(content, content=semantic, content_rowid=rowid);
    """),
    ("002_add_object_state", """
        -- Idempotent: skip if columns already exist (001 creates them for new DBs)
        -- Only needed for legacy databases created before Phase 1
    """),
]

# Individual ADD COLUMN statements for 002 — applied one at a time
# so each can fail independently without breaking the batch
_MIGRATION_002_COLUMNS = [
    "ALTER TABLE episodic ADD COLUMN objects_before TEXT DEFAULT '{}'",
    "ALTER TABLE episodic ADD COLUMN objects_after TEXT DEFAULT '{}'",
    "ALTER TABLE episodic ADD COLUMN object_changes TEXT DEFAULT '[]'",
]


class MigrationManager:
    """Track and apply schema migrations in version order."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version TEXT PRIMARY KEY,"
            "  applied_at TEXT NOT NULL"
            ")"
        )
        self.conn.commit()

    def _current_version(self) -> str:
        try:
            row = self.conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return ""
        return row["version"] if row else ""

    def migrate(self) -> list[str]:
        """Apply all pending migrations. Returns list of newly applied versions."""
        current = self._current_version()
        applied = []

        for version, sql in MIGRATIONS:
            if version <= current:
                continue
            try:
                if version == "002_add_object_state":
                    self._apply_002_idempotent()
                else:
                    self.conn.executescript(sql)
                self.conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(UTC).isoformat()),
                )
                self.conn.commit()
                applied.append(version)
                logger.info("migration_applied", version=version)
            except Exception:
                logger.error("migration_failed", version=version, exc_info=True)
                raise

        return applied

    def _apply_002_idempotent(self) -> None:
        """Apply 002 columns one at a time, skipping if already present."""
        for stmt in _MIGRATION_002_COLUMNS:
            try:
                self.conn.execute(stmt)
                self.conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

    def rollback_to(self, target_version: str) -> None:
        """Rollback schema to a target version (dev tool, not for production)."""
        current = self._current_version()
        if target_version >= current:
            return
        logger.warning("schema_rollback_requested",
                       current=current, target=target_version)
        self.conn.execute(
            "DELETE FROM schema_version WHERE version > ?",
            (target_version,),
        )
        self.conn.commit()
