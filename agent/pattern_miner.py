"""Cross-episode pattern mining for agent self-teaching.

Based on skills-as-continuous-learning.md: Agent discovers patterns across
episodes and proposes rules/skills. Human Taste (outsource-thinking-not-understanding.md)
makes the final decision — Agent proposes, human approves.

Three pattern types:
1. Error clusters: same error across same task_type → rule proposal
2. Correction clusters: same correction repeated → auto-skill proposal
3. Failure clusters: same verify failure → plan template enhancement

OS analogy: KSM (Kernel Same-page Merging) — find and merge duplicate patterns.
"""

from dataclasses import dataclass, field
from enum import StrEnum

import structlog

from .event_store import EventStore
from .events import EventType

logger = structlog.get_logger()


class ProposalType(StrEnum):
    RULE = "rule"           # Generate a dont-do rule
    SKILL = "skill"         # Create a reusable skill
    PLAN_HINT = "plan_hint" # Add to plan templates


@dataclass
class PatternProposal:
    """A pattern discovered across episodes, with a suggested action.

    Agent PROPOSES. Human APPROVES (or rejects). Never auto-execute.
    """
    type: ProposalType
    title: str
    description: str
    confidence: float             # 0.0 - 1.0
    evidence: list[str] = field(default_factory=list)  # Episode IDs that support this
    suggested_content: str = ""   # The proposed rule/skill/hint text

    def to_markdown(self) -> str:
        """Render as a human-readable proposal for approval."""
        conf_pct = int(self.confidence * 100)
        evidence_list = "\n".join(f"  - {e}" for e in self.evidence[:5])
        return (
            f"## [{self.type.value.upper()}] {self.title} (confidence: {conf_pct}%)\n\n"
            f"{self.description}\n\n"
            f"**Suggested content:**\n```\n{self.suggested_content}\n```\n\n"
            f"**Evidence:**\n{evidence_list}\n"
        )


class PatternMiner:
    """Discover patterns across episodes and generate learning proposals.

    Queries the event store for error/correction/failure events,
    clusters them by task_type, and generates proposals when
    a pattern repeats above a confidence threshold.
    """

    MIN_OCCURRENCES = 3       # Minimum repeats to form a pattern
    MIN_CONFIDENCE = 0.7      # Minimum confidence to propose

    def __init__(self, event_store: EventStore):
        self.event_store = event_store

    # ——— Mining ———

    def mine(self, recent_tasks: int = 100) -> list[PatternProposal]:
        """Run all mining analyses and return consolidated proposals."""
        proposals = []
        proposals.extend(self.mine_error_patterns(recent_tasks))
        proposals.extend(self.mine_correction_patterns(recent_tasks))
        proposals.extend(self.mine_failure_patterns(recent_tasks))
        return proposals

    def mine_error_patterns(self, limit: int = 100) -> list[PatternProposal]:
        """Find error types that repeat for the same task_type."""
        error_events = self.event_store.get_events_by_type(
            EventType.ERROR_OCCURRED, limit=limit,
        )
        if len(error_events) < self.MIN_OCCURRENCES:
            return []

        proposals = []
        # Group errors by (task inferred from context) + error_type
        error_groups: dict[tuple[str, str], list] = {}
        for e in error_events:
            error_type = e.payload.get("error_type", "Unknown")
            message = e.payload.get("message", "")
            key = (error_type, self._summarize(message))
            error_groups.setdefault(key, []).append(e)

        for (error_type, summary), events in error_groups.items():
            if len(events) < self.MIN_OCCURRENCES:
                continue
            confidence = min(0.95, len(events) / (len(events) + 2))
            if confidence < self.MIN_CONFIDENCE:
                continue

            task_ids = [e.task_id for e in events[:5]]
            proposals.append(PatternProposal(
                type=ProposalType.RULE,
                title=f"Recurring error: {error_type}",
                description=(
                    f"Error '{error_type}' ({summary}) occurred "
                    f"{len(events)} times across multiple tasks. "
                    f"Consider adding a dont-do rule or pre-check."
                ),
                confidence=confidence,
                evidence=task_ids,
                suggested_content=(
                    f"# Auto-generated rule proposal\n"
                    f"rules:\n"
                    f"  - id: auto-err-{_slug(error_type)}\n"
                    f"    description: 'Prevent: {summary}'\n"
                    f"    hook: [PRE_ACTION]\n"
                    f"    match:\n"
                    f"      error_type: {error_type}\n"
                    f"    action: WARN\n"
                    f"    message: 'This operation frequently causes "
                    f"{error_type}. Consider adding a pre-check.'\n"
                    f"    source: pattern_miner\n"
                ),
            ))

        return proposals

    def mine_correction_patterns(self, limit: int = 100) -> list[PatternProposal]:
        """Find corrections that repeat — candidate for permanent rules."""
        correction_events = self.event_store.get_events_by_type(
            EventType.CORRECTION_APPLIED, limit=limit,
        )
        if len(correction_events) < self.MIN_OCCURRENCES:
            return []

        proposals = []
        # Group by description similarity
        groups: dict[str, list] = {}
        for e in correction_events:
            desc = e.payload.get("description", "")
            summary = self._summarize(desc)
            groups.setdefault(summary, []).append(e)

        for summary, events in groups.items():
            if len(events) < self.MIN_OCCURRENCES:
                continue
            confidence = min(0.95, len(events) / (len(events) + 1))
            if confidence < self.MIN_CONFIDENCE:
                continue

            rule_ids = list(set(
                e.payload.get("rule_id", "") for e in events
            ))
            task_ids = [e.task_id for e in events[:5]]
            proposals.append(PatternProposal(
                type=ProposalType.SKILL,
                title=f"Recurring correction: {summary[:80]}",
                description=(
                    f"This correction was applied {len(events)} times "
                    f"(generated rules: {', '.join(r for r in rule_ids if r)}). "
                    f"Consider creating a permanent skill to prevent this issue."
                ),
                confidence=confidence,
                evidence=task_ids,
                suggested_content=(
                    f"# Auto-generated skill proposal\n"
                    f"---\n"
                    f"name: prevent-{_slug(summary)[:40]}\n"
                    f"description: >-\n"
                    f"  Auto-detected pattern: {summary[:200]}\n"
                    f"---\n\n"
                    f"# Prevent: {summary}\n\n"
                    f"This skill was proposed by the PatternMiner after "
                    f"detecting {len(events)} similar corrections.\n"
                ),
            ))

        return proposals

    def mine_failure_patterns(self, limit: int = 100) -> list[PatternProposal]:
        """Find recurring goal verification failures."""
        verify_events = self.event_store.get_events_by_type(
            EventType.GOAL_VERIFIED, limit=limit,
        )
        if len(verify_events) < self.MIN_OCCURRENCES:
            return []

        # Filter to only failed verifications
        failures = [
            e for e in verify_events
            if not e.payload.get("achieved", True)
        ]
        if len(failures) < self.MIN_OCCURRENCES:
            return []

        proposals = []
        # Group by explanation similarity
        groups: dict[str, list] = {}
        for e in failures:
            explanation = e.payload.get("explanation", "")
            summary = self._summarize(explanation)
            groups.setdefault(summary, []).append(e)

        for summary, events in groups.items():
            if len(events) < self.MIN_OCCURRENCES:
                continue
            confidence = min(0.9, len(events) / (len(events) + 3))
            if confidence < self.MIN_CONFIDENCE:
                continue

            task_ids = [e.task_id for e in events[:5]]
            proposals.append(PatternProposal(
                type=ProposalType.PLAN_HINT,
                title=f"Recurring verification failure: {summary[:80]}",
                description=(
                    f"Goal verification failed {len(events)} times with "
                    f"similar explanation. Consider adding a plan template "
                    f"step that addresses this common failure."
                ),
                confidence=confidence,
                evidence=task_ids,
                suggested_content=(
                    f"# Plan template hint\n"
                    f"# When planning tasks, add a verify step:\n"
                    f"# - Check: {summary[:200]}\n"
                ),
            ))

        return proposals

    # ——— Helpers ———

    @staticmethod
    def _summarize(text: str, max_len: int = 60) -> str:
        """Extract a short summary from error/correction text."""
        if not text:
            return "unknown"
        # Take first line or first N chars
        first_line = text.split("\n")[0].strip()
        if len(first_line) <= max_len:
            return first_line
        return first_line[:max_len - 3] + "..."

    @staticmethod
    def proposals_to_markdown(proposals: list[PatternProposal]) -> str:
        """Render all proposals as a human-reviewable markdown document."""
        if not proposals:
            return "No patterns discovered. Keep going — patterns emerge with more episodes."

        parts = [
            "# Pattern Mining Results\n",
            f"**{len(proposals)} proposals** found across episodes.\n",
            "> Review each proposal below. Agent proposes — you decide.\n",
        ]
        for p in proposals:
            parts.append(p.to_markdown())
            parts.append("\n---\n")
        return "\n".join(parts)


def _slug(text: str) -> str:
    """Simple slug generator for rule IDs."""
    import re
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text[:40].strip('-')
