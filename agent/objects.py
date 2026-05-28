"""Agent object model — how the agent perceives the world.

Each AgentObject represents an entity the agent can observe and manipulate.
State snapshots are captured before and after operations for verification.

Ontology-style extension (Data + Logic + Actions + Relations):
- Data: state_before / state_after snapshots
- Logic: constraints that govern valid operations on this object
- Actions: available operations with preconditions and side effects
- Relations: links to other objects (tested_by, imports, depends_on)
"""

from dataclasses import dataclass, field

# ——— State ———


@dataclass
class ObjectState:
    """Snapshot of a single object's state at a point in time."""
    observed_at: str
    properties: dict  # e.g. {"exists": True, "size": 1024, "branch": "main"}


# ——— Logic ———


@dataclass
class ObjectConstraint:
    """A constraint that governs valid operations on an object.

    Maps to the 'Logic' pillar in the Ontology Data-Logic-Actions triad.
    """
    description: str
    severity: str = "warning"  # "blocker" | "warning" | "info"
    check: str = ""            # Optional auto-check expression
    source: str = ""           # "dont_do" | "role" | "correction" | "tool_def"


# ——— Actions ———


@dataclass
class ObjectAction:
    """An action available on an object, with preconditions and side effects.

    Maps to the 'Actions' pillar in the Ontology triad.
    """
    name: str
    preconditions: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    tool: str = ""             # Tool that implements this action
    capability: str = ""       # Capability within the tool


# ——— Object ———


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

    # Ontology extension: Data + Logic + Actions + Relations
    constraints: list[ObjectConstraint] = field(default_factory=list)
    relations: dict[str, list[str]] = field(default_factory=dict)
    available_actions: list[ObjectAction] = field(default_factory=list)

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

    def context_for_llm(self) -> str:
        """Build a structured context string for LLM planning prompts.

        Includes state, constraints, relations, and available actions —
        giving the LLM the full Ontology context, not just raw data.
        """
        parts = [f"[{self.type}] {self.display_name} ({self.uri})"]

        # State
        state = self.state_before.properties if self.state_before else {}
        if state:
            parts.append(f"  State: {_format_properties(state)}")

        # Logic (constraints)
        if self.constraints:
            for c in self.constraints:
                tag = "BLOCKER" if c.severity == "blocker" else "warning"
                parts.append(f"  Constraint [{tag}]: {c.description}")

        # Relations
        if self.relations:
            for rel_type, targets in self.relations.items():
                parts.append(f"  {rel_type}: {', '.join(targets)}")

        # Actions
        if self.available_actions:
            action_names = [a.name for a in self.available_actions]
            parts.append(f"  Actions: {', '.join(action_names)}")

        return "\n".join(parts)


# ——— Helpers ———


def _format_properties(props: dict) -> str:
    """Format properties dict compactly."""
    if not props:
        return "{}"
    items = [f"{k}={_truncate(str(v), 80)}" for k, v in props.items()]
    return "{" + ", ".join(items[:10]) + "}"


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else s[:max_len - 3] + "..."


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


def build_object_context(objects: dict[str, "AgentObject"]) -> str:
    """Build a full Ontology context block for all observed objects.

    Injects into the planning prompt so the LLM sees the full
    Data + Logic + Actions + Relations picture.
    """
    if not objects:
        return ""

    blocks = []
    for uri, obj in objects.items():
        blocks.append(obj.context_for_llm())

    header = "## 对象上下文 (Ontology)\n"
    header += "以下是你可感知和操作的对象。每个对象包含状态、约束、关系和可用操作。\n"
    return header + "\n\n".join(blocks)
