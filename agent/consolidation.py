"""Memory consolidation: episodic → semantic. Phase 2.

Hybrid triggers: task end, task interrupt, count threshold, idle, manual.
LLM-driven: unconsolidated episodes → LLM extracts patterns → semantic store.
"""

import json
import time
import uuid
from datetime import UTC, datetime

import structlog

from agent.memory import MemoryStore, SemanticEntry

logger = structlog.get_logger()

CONSOLIDATION_PROMPT = """Analyze the following {n} task records and extract reusable knowledge.
Output ONLY valid JSON. Do not include markdown or explanations.

Rules:
1. Only extract patterns that would be useful for future tasks
2. If multiple records show the same pattern, merge them into one entry
3. Distinguish between:
   - "preference": user's habits/preferences (e.g. "uses pytest", "prefers small commits")
   - "fact": objective project facts (e.g. "database is PostgreSQL 15")
   - "pattern": recurring cause-effect (e.g. "changing auth.py requires full test suite")
4. Set confidence 0.5-1.0. Uncertain patterns get lower confidence.
5. If nothing useful to extract, return empty list.
6. Each entry gets a unique 'id' starting with 'sem-'.

Task records:
{episodes}

Output format:
[
  {{"id": "sem-001", "type": "preference",
    "content": "User prefers pytest", "confidence": 0.9,
    "source_episodes": ["t-001", "t-003"]}},
  {{"id": "sem-002", "type": "fact",
    "content": "Database is PostgreSQL 15", "confidence": 0.8,
    "source_episodes": ["t-002"]}}
]"""


class ConsolidationDaemon:
    """Background knowledge distillation. 类比: kswapd + LFS cleaner."""

    def __init__(self, store: MemoryStore, provider=None):
        self.store = store
        self._provider = provider  # LLMProvider, set after init
        self._last_consolidation: float = 0
        self._idle_since: float = 0
        self._interrupted_tasks: int = 0

    def set_provider(self, provider):
        self._provider = provider

    # ——— Trigger checks ———

    def on_task_end(self, interrupted: bool = False):
        """Called after every task (success, failure, or interruption)."""
        if interrupted:
            self._interrupted_tasks += 1
        self._idle_since = time.time()

    def should_consolidate(self, manual: bool = False) -> tuple[bool, str]:
        """Check if consolidation should run. Returns (should_run, reason)."""
        if manual:
            return True, "manual"

        unconsolidated = self.store.get_unconsolidated()
        count = len(unconsolidated)

        if count >= 10:
            return True, f"count_threshold: {count} unconsolidated"
        if count >= 5 and self._interrupted_tasks > 0:
            return True, f"mixed_threshold: {count} unconsolidated + {self._interrupted_tasks} interrupted"
        if count >= 3 and self._idle_since and (time.time() - self._idle_since) > 120:
            return True, "idle_120s"

        return False, ""

    # ——— Consolidation ———

    async def consolidate(self, manual: bool = False) -> dict:
        """Run one consolidation cycle.

        Returns: {"new": N, "updated": N, "merged": N, "deleted": N}
        """
        should_run, reason = self.should_consolidate(manual)
        if not should_run:
            return {"skipped": True, "reason": reason}

        episodes = self.store.get_unconsolidated()
        if not episodes:
            return {"skipped": True, "reason": "nothing to consolidate"}

        episode_ids = [e.task_id for e in episodes]
        logger.info("consolidation_start", reason=reason, episodes=len(episodes))

        # LLM extraction
        new_entries = await self._extract_patterns(episodes)
        if not new_entries:
            self.store.mark_consolidated(episode_ids)
            return {"new": 0, "updated": 0, "merged": 0, "deleted": 0}

        # Merge with existing
        stats = {"new": 0, "updated": 0, "merged": 0}
        for entry in new_entries:
            existing = self._find_similar(entry)
            if existing:
                # Merge: average confidence, combine sources
                existing.confidence = (existing.confidence + entry.confidence) / 2
                existing.source_episodes = list(set(
                    existing.source_episodes + entry.source_episodes
                ))
                existing.last_verified_at = datetime.now(UTC).isoformat()
                self.store.upsert_semantic(existing)
                stats["merged"] += 1
            else:
                self.store.upsert_semantic(entry)
                stats["new"] += 1

        # Cleanup
        deleted = self.store.delete_low_confidence(0.3)
        stats["deleted"] = deleted

        # Mark episodes as consolidated
        self.store.mark_consolidated(episode_ids)
        self._last_consolidation = time.time()
        self._interrupted_tasks = 0

        logger.info("consolidation_complete", **stats)
        return stats

    async def _extract_patterns(self, episodes) -> list[SemanticEntry]:
        """Send recent episodes to LLM, get distilled patterns."""
        if not self._provider:
            return self._rule_based_extract(episodes)

        episodes_text = self._format_episodes(episodes)
        prompt = CONSOLIDATION_PROMPT.format(
            n=len(episodes), episodes=episodes_text
        )

        try:
            resp = await self._provider.complete(prompt, max_tokens=2000)
            data = json.loads(self._extract_json(resp.content))
            entries = []
            for item in data:
                entries.append(SemanticEntry(
                    id=item.get("id", f"sem-{uuid.uuid4().hex[:8]}"),
                    type=item.get("type", "fact"),
                    content=item["content"],
                    confidence=float(item.get("confidence", 0.5)),
                    source_episodes=item.get("source_episodes", []),
                ))
            return entries
        except Exception as e:
            logger.warning("llm_consolidation_failed", error=str(e))
            return self._rule_based_extract(episodes)

    def _rule_based_extract(self, episodes) -> list[SemanticEntry]:
        """Fallback: rule-based pattern extraction without LLM."""
        entries = []
        tools_counter: dict[str, int] = {}
        for ep in episodes:
            for tool in ep.tools_used:
                tools_counter[tool] = tools_counter.get(tool, 0) + 1

        # Tool preference: used in >60% of episodes
        for tool, count in tools_counter.items():
            if count / len(episodes) > 0.6:
                entries.append(SemanticEntry(
                    id=f"sem-tool-{tool.replace('.', '-')}",
                    type="preference",
                    content=f"Frequently uses {tool}",
                    confidence=min(0.9, count / len(episodes)),
                    source_episodes=[e.task_id for e in episodes],
                ))

        return entries

    def _find_similar(self, entry: SemanticEntry) -> SemanticEntry | None:
        """Find existing semantic entry similar to new one."""
        existing = self.store.list_semantic(entry_type=entry.type)
        for ex in existing:
            # Simple overlap check
            words_new = set(entry.content.lower().split())
            words_ex = set(ex.content.lower().split())
            if len(words_new & words_ex) > len(words_new) * 0.5:
                return ex
        return None

    def _format_episodes(self, episodes) -> str:
        lines = []
        for ep in episodes:
            lines.append(
                f"[{ep.task_id}] {ep.task_type}: {ep.task_summary}\n"
                f"  tools: {', '.join(ep.tools_used) if ep.tools_used else 'none'}\n"
                f"  steps: {ep.steps}, success: {ep.success}"
                f"{', error: ' + ep.error if ep.error else ''}"
            )
        return "\n\n".join(lines)

    def _extract_json(self, text: str) -> str:
        """Extract JSON array from LLM response (may have markdown wrap)."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:]) if len(lines) > 1 else text
            if text.endswith("```"):
                text = text[:-3]
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            return text[start:end + 1]
        return text
