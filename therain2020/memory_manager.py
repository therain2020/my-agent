"""Claude Code-style memory: MEMORY.md index + per-topic .md files.

~/.therain2020-agent/memory/
├── MEMORY.md        ← index, auto-loaded every session
├── tools.md         ← agent-created tools inventory
├── sessions.md      ← recent session summaries (/resume)
├── learnings.md     ← lessons from failures
└── preferences.md   ← user preferences
"""

from __future__ import annotations

import re
import time
from pathlib import Path


class MemoryManager:
    def __init__(self, base_dir: Path | None = None):
        base = base_dir or Path.home() / ".therain2020-agent"
        self.memory_dir = base / "memory"
        self.index_path = self.memory_dir / "MEMORY.md"

    def ensure(self):
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.index_path.write_text("# Agent Memory\n\n", encoding="utf-8")

    # —— load ——

    def load_context(self) -> str:
        """Read MEMORY.md + referenced files. Return context for system prompt."""
        if not self.index_path.exists():
            return ""
        index = self.index_path.read_text(encoding="utf-8")
        entries = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", index)
        parts = [index]
        for title, path in entries[:8]:
            fp = self.memory_dir / path
            if fp.exists():
                content = fp.read_text(encoding="utf-8")
                parts.append(f"## {title}\n\n{content}")
        return "\n---\n".join(parts)

    # —— record ——

    def record_tool(self, name: str, description: str, code_summary: str = ""):
        """Agent created a new tool."""
        self.ensure()
        ts = time.strftime("%Y-%m-%d %H:%M")
        entry = (
            f"## {name}\n"
            f"**Created**: {ts}\n\n"
            f"**Description**: {description}\n\n"
        )
        if code_summary:
            entry += f"**Code**: {code_summary}\n\n"
        self._upsert_memory("tools.md", "Created Tools", entry)

    def record_session(self, task: str, success: bool, steps: int,
                       tools: list[str], duration: float):
        """Session ended — append summary."""
        self.ensure()
        ts = time.strftime("%Y-%m-%d %H:%M")
        status = "✓" if success else "✗"
        tools_str = ", ".join(tools) if tools else "none"
        entry = (
            f"## {ts}\n"
            f"**Task**: {task}\n"
            f"**Result**: {status} — {steps} steps, {duration:.1f}s\n"
            f"**Tools**: {tools_str}\n\n"
        )
        self._upsert_memory("sessions.md", "Session History",
                            entry, prepend=False)

    def record_learning(self, lesson_type: str, content: str, source: str = ""):
        """Learned from success or failure."""
        self.ensure()
        ts = time.strftime("%Y-%m-%d %H:%M")
        entry = (
            f"## [{lesson_type}] {ts}\n"
            f"**Lesson**: {content}\n"
        )
        if source:
            entry += f"**Source**: {source}\n"
        entry += "\n"
        self._upsert_memory("learnings.md", "Learnings", entry, prepend=False)

    # —— internal ——

    def _upsert_memory(self, filename: str, title: str, content: str,
                       prepend: bool = True):
        """Write content to a memory file. Update MEMORY.md index."""
        fp = self.memory_dir / filename
        if fp.exists() and not prepend:
            existing = fp.read_text(encoding="utf-8")
            # Keep last 20 entries, trim old ones
            entries = existing.split("\n## ")[1:]  # skip header
            existing = "\n## ".join([""] + entries[-19:])
            fp.write_text(existing + "\n" + content, encoding="utf-8")
        elif prepend:
            fp.write_text(content, encoding="utf-8")
        else:
            fp.write_text(content, encoding="utf-8")
        self._update_index(filename, title)

    def _update_index(self, filename: str, title: str):
        idx = self.index_path.read_text(encoding="utf-8")
        hook = f"- [{title}]({filename})"
        if hook in idx:
            return
        line = f"{hook} — auto-maintained\n"
        if "MEMORY.md" in idx:
            idx = idx.rstrip() + "\n" + line
        else:
            idx += line
        self.index_path.write_text(idx, encoding="utf-8")
