"""Agent tool editing interface. 类比: ptrace system call.

Provides the agent with structured read/write access to the tool system.
This is the surface through which the agent performs self-healing:
- Detects missing capability → writes helper → retries
- Detects silent failure → writes verify function → retries
"""

from __future__ import annotations

import structlog
import yaml

from .evolution import EvolutionAction, ToolEvolutionManager

logger = structlog.get_logger()

# What the agent can do to the tool system
EDIT_CAPABILITIES = [
    {"name": "read_tool", "description": "Read a tool's full source code", "safety": "safe"},
    {"name": "add_verify", "description": "Add or update a verify hook on a capability", "safety": "safe"},
    {"name": "add_helper", "description": "Add a new helper function to a tool", "safety": "caution"},
    {"name": "modify_capability", "description": "Modify an existing capability's implementation", "safety": "caution"},
    {"name": "get_edit_history", "description": "Get history of all agent edits", "safety": "safe"},
    {"name": "rollback_tool", "description": "Rollback a tool to a previous version", "safety": "dangerous"},
]


class AgentToolEditor:
    """Safe editing surface for agent-driven tool evolution.

    类比: ptrace — one process safely inspects/modifies another.
    """

    def __init__(self, evolution: ToolEvolutionManager):
        self.evolution = evolution

    # === Public API (exposed as tool capabilities to the agent) ===

    def read_tool(self, tool_name: str) -> dict:
        """Read a tool's complete source. Agent uses this to understand existing code."""
        return self.evolution.read_tool_source(tool_name)

    def add_verify(
        self,
        tool_name: str,
        capability_name: str,
        verify_function: str,
        episode_id: str,
        reason: str = "",
    ) -> dict:
        """Add a verification hook to a capability.

        This is the primary path for 十-A auto-healing:
        Agent detects silent failure → writes verify function → commits.
        """
        source = self.evolution.read_tool_source(tool_name)
        if "error" in source:
            return source

        # 1. Write the verify function to a .py file
        safe_cap = capability_name.replace("-", "_").replace(" ", "_")
        verify_filename = f"verify_{safe_cap}.py"
        changes = {verify_filename: verify_function}

        # 2. Update tool.md metadata to add the verify field
        meta = source.get("metadata", {})
        caps = meta.get("capabilities", [])
        for cap in caps:
            if cap.get("name") == capability_name:
                cap["verify"] = {
                    "function": f"{verify_filename}:verify_{safe_cap}",
                    "auto_generated": True,
                    "generated_by": episode_id,
                }
                break
        else:
            return {
                "success": False,
                "message": f"Capability '{capability_name}' not found on tool '{tool_name}'",
            }

        new_tool_md = _rebuild_tool_md(meta, source.get("body", ""))
        changes["tool.md"] = new_tool_md

        # 3. Stage, validate, and commit
        record = self.evolution.stage_change(
            tool_name=tool_name,
            action=EvolutionAction.ADD_VERIFY,
            changes=changes,
            episode_id=episode_id,
            description=f"Add verify hook for {capability_name}: {reason}",
        )

        ok = self.evolution.validate_and_commit(record.id)
        return {
            "success": ok,
            "record_id": record.id,
            "message": (
                f"Verify hook for {tool_name}.{capability_name} "
                f"{'added' if ok else 'failed validation'}"
            ),
        }

    def add_helper(
        self,
        tool_name: str,
        helper_name: str,
        helper_code: str,
        episode_id: str,
        reason: str = "",
    ) -> dict:
        """Add a new helper function to a tool. Core self-healing path.

        When the agent encounters a missing capability, it writes a new helper
        function to fill the gap.
        """
        source = self.evolution.read_tool_source(tool_name)
        if "error" in source:
            return source

        safe_name = helper_name.replace("-", "_").replace(" ", "_")
        filename = f"{safe_name}.py"
        changes = {filename: helper_code}

        # Update tool.md metadata to track agent-added helpers
        meta = source.get("metadata", {})
        if "agent_helpers" not in meta:
            meta["agent_helpers"] = []
        meta["agent_helpers"].append({
            "name": helper_name,
            "file": filename,
            "added_by": episode_id,
            "reason": reason,
        })

        new_tool_md = _rebuild_tool_md(meta, source.get("body", ""))
        changes["tool.md"] = new_tool_md

        record = self.evolution.stage_change(
            tool_name=tool_name,
            action=EvolutionAction.CREATE,
            changes=changes,
            episode_id=episode_id,
            description=f"Add helper {helper_name}: {reason}",
        )

        ok = self.evolution.validate_and_commit(record.id)
        return {
            "success": ok,
            "record_id": record.id,
            "message": f"Helper {helper_name} {'added' if ok else 'failed validation'}",
        }

    def get_edit_history(self, tool_name: str | None = None) -> list[dict]:
        """Get history of all agent edits."""
        records = self.evolution.get_history(tool_name)
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "action": r.action.value,
                "target": r.target,
                "episode_id": r.episode_id,
                "description": r.description,
                "verified": r.verified,
            }
            for r in records
        ]

    def rollback_tool(self, tool_name: str, steps: int = 1) -> dict:
        """Rollback a tool to a previous version."""
        record = self.evolution.rollback(tool_name, steps)
        if record:
            return {"success": True, "record_id": record.id, "message": record.description}
        return {"success": False, "message": f"Rollback of {tool_name} failed"}


def _rebuild_tool_md(meta: dict, body: str) -> str:
    """Rebuild tool.md from metadata dict and markdown body."""
    yaml_str = yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False)
    content = f"---\n{yaml_str}---"
    if body:
        content += f"\n{body}"
    return content
