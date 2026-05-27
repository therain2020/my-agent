"""Agent object model — how the agent perceives the world.

Each AgentObject represents an entity the agent can observe and manipulate.
State snapshots are captured before and after operations for verification.
"""

from dataclasses import dataclass, field


@dataclass
class ObjectState:
    """Snapshot of a single object's state at a point in time."""
    observed_at: str
    properties: dict  # e.g. {"exists": True, "size": 1024, "branch": "main"}


@dataclass
class AgentObject:
    """An entity the agent can perceive and act upon.

    URI is the canonical identifier (e.g. "file://src/main.py", "git://repo").
    """
    uri: str
    type: str              # "file" | "directory" | "git-repo" | "database" | "service"
    display_name: str = ""
    state_before: ObjectState | None = None
    state_after: ObjectState | None = None
    observation_tools: list[str] = field(default_factory=list)
    manipulation_tools: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.uri

    @property
    def state_changed(self) -> bool:
        if not self.state_before or not self.state_after:
            return False
        return self.state_before.properties != self.state_after.properties

    @property
    def diff(self) -> dict:
        """Compute state change differences."""
        if not self.state_before or not self.state_after:
            return {}
        before = self.state_before.properties
        after = self.state_after.properties
        changes = {}
        all_keys = set(before.keys()) | set(after.keys())
        for k in all_keys:
            bv = before.get(k)
            av = after.get(k)
            if bv != av:
                changes[k] = {"before": bv, "after": av}
        return changes


def resolve_object_type(uri: str, tool_objects: list[str]) -> str:
    """Infer object type from URI scheme or tool objects list."""
    if "://" in uri:
        return uri.split("://")[0]  # file, git, db, etc.
    if tool_objects:
        return tool_objects[0]
    return "unknown"


def extract_state_properties(result) -> dict:
    """Extract structured state properties from a tool result."""
    import json
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except (json.JSONDecodeError, ValueError):
            return {"raw_output": result[:500]}
    return {"raw_output": str(result)[:500]}
