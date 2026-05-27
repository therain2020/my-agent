"""Memory system. Phase 1: episodic log only (Markdown append-only).

Phase 1 records: timestamp, task type, task summary, tools used, result.

Phase 2 will add: semantic memory + consolidation + LRU cache.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()


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
    non_set_changes: list[str] = field(default_factory=list)
    timestamp: str = ""


class EpisodicMemory:
    """Append-only episodic log. 类比: WAL / append-only log.

    Records each task execution to a Markdown file.
    Directory structure: memory/episodic/YYYY-MM/
    """

    def __init__(self, base_path: str = "./memory/episodic"):
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    def log_episode(self, entry: EpisodeEntry) -> Path:
        """Record a task execution episode.

        Appends to the current month's log file.
        """
        entry.timestamp = datetime.now(timezone.utc).isoformat()

        month_dir = self._base / datetime.now().strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)

        log_file = month_dir / "episodes.md"

        # Build markdown entry
        status = "✓" if entry.success else "✗"
        md_entry = f"""### {entry.timestamp} | {entry.task_type} | {status}

**任务**: {entry.task_summary}
**工具**: {', '.join(entry.tools_used) if entry.tools_used else 'none'}
**步骤数**: {entry.steps}
**结果**: {'成功' if entry.success else '失败'}
{chr(10) + '**错误**: ' + entry.error if entry.error else ''}
{chr(10) + '**非集变动**: ' + ', '.join(entry.non_set_changes) if entry.non_set_changes else ''}

---
"""
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(md_entry)

        logger.info("episode_logged", task_id=entry.task_id, file=str(log_file))
        return log_file

    def get_recent(self, count: int = 10) -> list[EpisodeEntry]:
        """Get recent episodes (best effort from current month file)."""
        month_dir = self._base / datetime.now().strftime("%Y-%m")
        if not month_dir.exists():
            return []

        entries = []
        log_file = month_dir / "episodes.md"
        if log_file.exists():
            # Parse markdown entries (simplified)
            content = log_file.read_text(encoding="utf-8")
            for block in content.split("---"):
                block = block.strip()
                if block.startswith("### "):
                    entry = self._parse_block(block)
                    if entry:
                        entries.append(entry)

        return entries[-count:]

    def stats(self) -> dict:
        """Basic statistics."""
        entries = self.get_recent(100)
        total = len(entries)
        if not total:
            return {"total_episodes": 0}

        success_count = sum(1 for e in entries if e.success)
        return {
            "total_episodes": total,
            "success_rate": round(success_count / total * 100, 1) if total else 0,
            "avg_steps": round(sum(e.steps for e in entries) / total, 1),
        }

    def _parse_block(self, block: str) -> Optional[EpisodeEntry]:
        """Parse a single episode block from markdown."""
        lines = block.split("\n")
        if not lines:
            return None

        header = lines[0]
        # Format: "### 2026-05-27T... | goal | ✓"
        parts = header.replace("### ", "").split("|")
        if len(parts) < 3:
            return None

        timestamp = parts[0].strip()
        task_type = parts[1].strip()
        success = "✓" in parts[2]

        task_summary = ""
        tools_used = []
        steps = 0
        error = ""

        for line in lines[1:]:
            line = line.strip()
            if line.startswith("**任务**:"):
                task_summary = line.replace("**任务**:", "").strip()
            elif line.startswith("**工具**:"):
                tools_str = line.replace("**工具**:", "").strip()
                if tools_str and tools_str != "none":
                    tools_used = [t.strip() for t in tools_str.split(",")]
            elif line.startswith("**步骤数**:"):
                try:
                    steps = int(line.replace("**步骤数**:", "").strip())
                except ValueError:
                    pass
            elif line.startswith("**错误**:"):
                error = line.replace("**错误**:", "").strip()

        return EpisodeEntry(
            task_id=f"parsed-{timestamp}",
            task_type=task_type,
            task_summary=task_summary,
            tools_used=tools_used,
            steps=steps,
            success=success,
            error=error,
            timestamp=timestamp,
        )
