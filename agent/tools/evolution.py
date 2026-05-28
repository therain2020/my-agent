"""Tool evolution manager. 类比: kpatch — runtime kernel patching.

Manages agent-driven tool modifications:
- Safe read/write of tool definitions and implementations
- Git-based version control for all agent modifications
- Validation gate before hot-reload
- Rollback on failure
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()


class EvolutionAction(Enum):
    CREATE = "create"
    MODIFY = "modify"
    ADD_VERIFY = "add_verify"
    DELETE = "delete"
    ROLLBACK = "rollback"


@dataclass
class EvolutionRecord:
    """A single tool modification record."""

    id: str
    timestamp: str
    action: EvolutionAction
    target: str  # tool name
    episode_id: str
    description: str
    diff: str = ""
    snapshot_hash: str = ""
    verified: bool = False


class ToolEvolutionManager:
    """Manages agent-driven tool evolution. 类比: kpatch runtime patching."""

    def __init__(self, tools_dir: str = "tools"):
        self.tools_dir = Path(tools_dir)
        self.generated_dir = self.tools_dir / ".generated"
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self._history: list[EvolutionRecord] = []
        self._pending: dict[str, EvolutionRecord] = {}

    # === Safe editing API for agents ===

    def read_tool_source(self, tool_name: str) -> dict:
        """Read complete source of a tool (tool.md + implementations).

        Returns a structured dict the agent can understand and modify.
        """
        for base in [self.tools_dir, self.generated_dir]:
            tool_md = base / tool_name / "tool.md"
            if tool_md.exists():
                break
        else:
            return {"error": f"Tool '{tool_name}' not found"}

        raw = tool_md.read_text(encoding="utf-8")
        parts = raw.split("---", 2)
        meta = yaml.safe_load(parts[1]) if len(parts) >= 2 else {}
        body = parts[2] if len(parts) >= 3 else ""

        impls = {}
        tool_dir = tool_md.parent
        for py_file in sorted(tool_dir.glob("*.py")):
            impls[py_file.name] = py_file.read_text(encoding="utf-8")

        return {
            "name": tool_name,
            "metadata": meta,
            "body": body,
            "implementations": impls,
            "path": str(tool_md),
        }

    def stage_change(
        self,
        tool_name: str,
        action: EvolutionAction,
        changes: dict,  # {"tool.md": "new content", "helpers.py": "..."}
        episode_id: str,
        description: str,
    ) -> EvolutionRecord:
        """Stage a tool change. Does NOT apply yet — goes through validation gate."""
        snapshot = self._compute_state_hash(tool_name)

        record = EvolutionRecord(
            id=f"evol-{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(UTC).isoformat(),
            action=action,
            target=tool_name,
            episode_id=episode_id,
            description=description,
            snapshot_hash=snapshot,
        )

        stage_dir = self.generated_dir / tool_name
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        stage_dir.mkdir(parents=True, exist_ok=True)

        for file_path, content in changes.items():
            target_path = stage_dir / file_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")

        self._pending[record.id] = record
        return record

    def validate_and_commit(self, record_id: str) -> bool:
        """Validation gate before applying agent changes.

        Checks:
        1. YAML validity for tool.md
        2. Python syntax for .py files
        3. Commit via git
        """
        record = self._pending.pop(record_id, None)
        if not record:
            return False

        stage_dir = self.generated_dir / record.target

        # Validate YAML in tool.md
        tool_md = stage_dir / "tool.md"
        if tool_md.exists():
            try:
                raw = tool_md.read_text(encoding="utf-8")
                if "---" in raw:
                    parts = raw.split("---", 2)
                    yaml.safe_load(parts[1])
            except yaml.YAMLError as e:
                logger.error("evolution_yaml_invalid", error=str(e))
                return False

        # Validate Python syntax
        for py_file in stage_dir.glob("*.py"):
            try:
                compile(py_file.read_text(encoding="utf-8"), str(py_file), "exec")
            except SyntaxError as e:
                logger.error("evolution_syntax_error", file=str(py_file), error=str(e))
                return False

        # Compute diff
        record.diff = self._compute_diff(record.target, stage_dir)

        # Copy staged files to live location
        live_dir = self.tools_dir / record.target
        if live_dir.exists():
            shutil.rmtree(live_dir)
        shutil.copytree(stage_dir, live_dir)

        # Clean up staging
        shutil.rmtree(stage_dir)

        # Git commit
        self._git_commit(record)

        record.verified = True
        self._history.append(record)
        logger.info(
            "evolution_committed",
            record_id=record_id,
            action=record.action.value,
            target=record.target,
        )
        return True

    def rollback(self, tool_name: str, steps: int = 1) -> EvolutionRecord | None:
        """Rollback N evolution steps using git history."""
        tool_dir = self.tools_dir / tool_name
        try:
            subprocess.run(
                ["git", "checkout", f"HEAD~{steps}", "--", str(tool_dir)],
                capture_output=True, text=True, check=True,
            )
            subprocess.run(
                ["git", "commit", "-m",
                 f"tool(evolution): rollback {tool_name} {steps} step(s)"],
                capture_output=True, text=True, check=True,
            )
            record = EvolutionRecord(
                id=f"evol-rb-{uuid.uuid4().hex[:8]}",
                timestamp=datetime.now(UTC).isoformat(),
                action=EvolutionAction.ROLLBACK,
                target=tool_name,
                episode_id="",
                description=f"Rolled back {steps} step(s)",
            )
            self._history.append(record)
            return record
        except subprocess.CalledProcessError as e:
            logger.error("evolution_rollback_failed", error=str(e))
            return None

    def get_history(self, tool_name: str | None = None) -> list[EvolutionRecord]:
        """Get evolution history, optionally filtered by tool."""
        if tool_name:
            return [r for r in self._history if r.target == tool_name]
        return list(self._history)

    # === Internal ===

    def _compute_state_hash(self, tool_name: str) -> str:
        tool_dir = self.tools_dir / tool_name
        if not tool_dir.exists():
            return ""
        hasher = hashlib.sha256()
        for f in sorted(tool_dir.rglob("*")):
            if f.is_file():
                hasher.update(f.read_bytes())
        return hasher.hexdigest()[:16]

    def _compute_diff(self, tool_name: str, stage_dir: Path) -> str:
        tool_dir = self.tools_dir / tool_name
        if not tool_dir.exists():
            return "(new tool — no diff baseline)"
        try:
            result = subprocess.run(
                ["git", "diff", "--no-index", str(tool_dir), str(stage_dir)],
                capture_output=True, text=True,
            )
            return result.stdout[:5000]
        except subprocess.CalledProcessError:
            return "(diff unavailable)"

    def _git_commit(self, record: EvolutionRecord) -> None:
        tool_dir = self.tools_dir / record.target
        try:
            subprocess.run(
                ["git", "add", str(tool_dir)],
                capture_output=True, check=True,
            )
            msg = (
                f"tool(evolution): {record.action.value} {record.target}\n\n"
                f"{record.description}\n\n"
                f"Episode: {record.episode_id}"
            )
            subprocess.run(
                ["git", "commit", "-m", msg],
                capture_output=True, check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error("evolution_git_failed", error=str(e))
