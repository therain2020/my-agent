"""Skill storage and retrieval. SQLite-backed with FTS5 search."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import structlog

from .models import Skill, SkillFeedback, SkillLevel

logger = structlog.get_logger()


class SkillRepository:
    """Skill storage with full-text search."""

    def __init__(self, db_path: str = "data/skills.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                task_type TEXT NOT NULL,
                domain TEXT NOT NULL,
                triggers TEXT NOT NULL DEFAULT '[]',
                level INTEGER NOT NULL DEFAULT 1,
                approach TEXT NOT NULL,
                preconditions TEXT DEFAULT '[]',
                postconditions TEXT DEFAULT '[]',
                success_rate REAL DEFAULT 0.0,
                uses INTEGER DEFAULT 0,
                created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                last_used TEXT DEFAULT '',
                score INTEGER DEFAULT 0,
                retired INTEGER DEFAULT 0,
                merged_from TEXT DEFAULT '[]',
                pii_checked INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS skill_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                reason TEXT NOT NULL,
                episode_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (skill_id) REFERENCES skills(id)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
                name, task_type, domain, triggers, approach, tags,
                content='skills', content_rowid='rowid'
            );

            CREATE INDEX IF NOT EXISTS idx_skills_task_type ON skills(task_type);
            CREATE INDEX IF NOT EXISTS idx_skills_domain ON skills(domain);
            CREATE INDEX IF NOT EXISTS idx_skills_score ON skills(score);
            CREATE INDEX IF NOT EXISTS idx_skills_retired ON skills(retired);
        """)
        self.conn.commit()

    def save(self, skill: Skill) -> bool:
        try:
            self.conn.execute(
                """INSERT OR REPLACE INTO skills
                   (id, name, task_type, domain, triggers, level, approach,
                    preconditions, postconditions, success_rate, uses, created_by,
                    created_at, last_used, score, retired, merged_from, pii_checked, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    skill.id, skill.name, skill.task_type, skill.domain,
                    json.dumps(skill.triggers, ensure_ascii=False),
                    skill.level.value, skill.approach,
                    json.dumps(skill.preconditions, ensure_ascii=False),
                    json.dumps(skill.postconditions, ensure_ascii=False),
                    skill.success_rate, skill.uses, skill.created_by,
                    skill.created_at, skill.last_used, skill.score,
                    1 if skill.retired else 0,
                    json.dumps(skill.merged_from),
                    1 if skill.pii_checked else 0,
                    json.dumps(skill.tags, ensure_ascii=False),
                ),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error("skill_save_failed", error=str(e))
            return False

    def search(self, query: str, limit: int = 5,
               task_type: str | None = None) -> list[Skill]:
        """Full-text search for skills matching the query."""
        sql = """
            SELECT s.* FROM skills s
            JOIN skills_fts fts ON s.rowid = fts.rowid
            WHERE skills_fts MATCH ?
            AND s.retired = 0
        """
        params: list = [query]
        if task_type:
            sql += " AND s.task_type = ?"
            params.append(task_type)
        sql += " ORDER BY s.score DESC, s.success_rate DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_skill(r) for r in rows]

    def find_by_triggers(self, text: str, limit: int = 5) -> list[Skill]:
        """Find skills whose triggers match the input text."""
        rows = self.conn.execute(
            "SELECT * FROM skills WHERE retired = 0 ORDER BY score DESC"
        ).fetchall()

        matched = []
        for row in rows:
            skill = self._row_to_skill(row)
            for trigger in skill.triggers:
                if trigger.lower() in text.lower():
                    matched.append(skill)
                    break

        matched.sort(key=lambda s: s.quality_score, reverse=True)
        return matched[:limit]

    def find_near_duplicates(self, skill: Skill, threshold: float = 0.7) -> list[Skill]:
        """Find near-duplicate skills for merging."""
        rows = self.conn.execute(
            "SELECT * FROM skills WHERE task_type = ? AND domain = ? "
            "AND retired = 0 AND id != ?",
            (skill.task_type, skill.domain, skill.id),
        ).fetchall()

        candidates = [self._row_to_skill(r) for r in rows]
        duplicates = []
        for c in candidates:
            overlap = len(set(skill.triggers) & set(c.triggers))
            total = max(1, len(set(skill.triggers) | set(c.triggers)))
            if overlap / total >= threshold:
                duplicates.append(c)
        return duplicates

    def retire(self, skill_id: str) -> bool:
        self.conn.execute("UPDATE skills SET retired = 1 WHERE id = ?", (skill_id,))
        self.conn.commit()
        return True

    def get(self, skill_id: str) -> Skill | None:
        row = self.conn.execute(
            "SELECT * FROM skills WHERE id = ?", (skill_id,)
        ).fetchone()
        return self._row_to_skill(row) if row else None

    def get_active(self, limit: int = 50) -> list[Skill]:
        rows = self.conn.execute(
            "SELECT * FROM skills WHERE retired = 0 ORDER BY score DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_skill(r) for r in rows]

    def _row_to_skill(self, row) -> Skill:
        return Skill(
            id=row["id"],
            name=row["name"],
            task_type=row["task_type"],
            domain=row["domain"],
            triggers=json.loads(row["triggers"]),
            level=SkillLevel(row["level"]),
            approach=row["approach"],
            preconditions=json.loads(row["preconditions"]),
            postconditions=json.loads(row["postconditions"]),
            success_rate=row["success_rate"],
            uses=row["uses"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            last_used=row["last_used"],
            score=row["score"],
            retired=bool(row["retired"]),
            merged_from=json.loads(row["merged_from"]),
            pii_checked=bool(row["pii_checked"]),
            tags=json.loads(row["tags"]),
        )

    def get_feedback(self, skill_id: str) -> list[SkillFeedback]:
        rows = self.conn.execute(
            "SELECT * FROM skill_feedback WHERE skill_id = ? ORDER BY timestamp",
            (skill_id,),
        ).fetchall()
        return [
            SkillFeedback(
                rating=r["rating"], reason=r["reason"],
                episode_id=r["episode_id"], timestamp=r["timestamp"],
            )
            for r in rows
        ]
