"""Event schema for Event Sourcing memory system.

Each agent action produces an immutable event appended to the event log.
Current state is computed by replaying events from the log.

Consistency model (from strict-vs-eventual-consistency.md):
- Safety-critical: RuleAdded, RuleModified → synchronous, immediate visibility
- Observation: ObjectObserved, ToolCalled, GoalVerified → eventual consistency OK

Event types follow the event-vs-command.md distinction:
- Events (past-tense): report facts that already happened
- Commands (imperative): not stored as events; only their results are
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class EventType(StrEnum):
    """All agent event types in the event log."""
    GOAL_STARTED = "goal_started"
    OBJECT_OBSERVED = "object_observed"
    PLAN_GENERATED = "plan_generated"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    CORRECTION_APPLIED = "correction_applied"
    RULE_ADDED = "rule_added"          # Safety-critical: synchronous
    RULE_MODIFIED = "rule_modified"     # Safety-critical: synchronous
    GOAL_VERIFIED = "goal_verified"
    GOAL_COMPLETED = "goal_completed"
    ERROR_OCCURRED = "error_occurred"


# ——— Event data classes ———


@dataclass
class AgentEvent:
    """Base event. All agent events have these fields."""
    event_type: EventType
    task_id: str
    timestamp: str = ""
    payload: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


# ——— Factory helpers ———


def goal_started(task_id: str, goal: str, mode: str = "goal") -> AgentEvent:
    return AgentEvent(
        event_type=EventType.GOAL_STARTED,
        task_id=task_id,
        payload={"goal": goal[:500], "mode": mode},
    )


def object_observed(task_id: str, uri: str, obj_type: str,
                    properties: dict) -> AgentEvent:
    return AgentEvent(
        event_type=EventType.OBJECT_OBSERVED,
        task_id=task_id,
        payload={"uri": uri, "type": obj_type, "properties": properties},
    )


def plan_generated(task_id: str, steps: list[dict]) -> AgentEvent:
    return AgentEvent(
        event_type=EventType.PLAN_GENERATED,
        task_id=task_id,
        payload={"step_count": len(steps), "steps": steps},
    )


def tool_called(task_id: str, tool: str, capability: str,
                params: dict) -> AgentEvent:
    return AgentEvent(
        event_type=EventType.TOOL_CALLED,
        task_id=task_id,
        payload={"tool": tool, "capability": capability, "params": params},
    )


def tool_result(task_id: str, tool: str, capability: str,
                result_summary: str, success: bool = True) -> AgentEvent:
    return AgentEvent(
        event_type=EventType.TOOL_RESULT,
        task_id=task_id,
        payload={
            "tool": tool, "capability": capability,
            "result": result_summary[:500], "success": success,
        },
    )


def correction_applied(task_id: str, corr_id: str, rule_id: str,
                       description: str) -> AgentEvent:
    return AgentEvent(
        event_type=EventType.CORRECTION_APPLIED,
        task_id=task_id,
        payload={"corr_id": corr_id, "rule_id": rule_id,
                 "description": description[:200]},
    )


def rule_added(task_id: str, rule_id: str, description: str) -> AgentEvent:
    """Safety-critical event — must be synchronously visible."""
    return AgentEvent(
        event_type=EventType.RULE_ADDED,
        task_id=task_id,
        payload={"rule_id": rule_id, "description": description[:200]},
    )


def goal_verified(task_id: str, achieved: bool, confidence: float,
                  explanation: str = "") -> AgentEvent:
    return AgentEvent(
        event_type=EventType.GOAL_VERIFIED,
        task_id=task_id,
        payload={"achieved": achieved, "confidence": confidence,
                 "explanation": explanation[:300]},
    )


def goal_completed(task_id: str, success: bool, steps: int,
                   duration_seconds: float) -> AgentEvent:
    return AgentEvent(
        event_type=EventType.GOAL_COMPLETED,
        task_id=task_id,
        payload={"success": success, "steps": steps,
                 "duration_seconds": duration_seconds},
    )


def error_occurred(task_id: str, error_type: str,
                   message: str) -> AgentEvent:
    return AgentEvent(
        event_type=EventType.ERROR_OCCURRED,
        task_id=task_id,
        payload={"error_type": error_type, "message": message[:500]},
    )


# ——— Safety-critical event types (need synchronous visibility) ———

SAFETY_CRITICAL_EVENTS = {EventType.RULE_ADDED, EventType.RULE_MODIFIED}
