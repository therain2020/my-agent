"""Context virtual memory manager. Phase 2.

类比: MMU + page replacement.
Manages what's in the LLM context window — loading, evicting, compressing.
"""

import time
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class ContextPage:
    id: str
    content: str
    tokens: int
    priority: int          # 1=永驻 2=必需 3=按需 4=可踢
    last_accessed: float = 0.0
    access_count: int = 0
    in_context: bool = True
    source: str = ""       # Not in context? Where to reload from.
    eviction_policy: str = "discard"  # discard | compress | persist


class ContextManager:
    """Virtual memory for LLM context. 类比: MMU + LRU page replacement."""

    def __init__(self, max_tokens: int = 100000):
        self.max_tokens = max_tokens
        self.pages: dict[str, ContextPage] = {}
        self.in_context_tokens: int = 0
        self.page_faults: int = 0
        self.evictions: int = 0

    def load(self, page_id: str, content: str, priority: int = 3,
             eviction_policy: str = "discard", source: str = "") -> str:
        """Load a page into context. Returns the content (may be truncated).

        If context is full, evicts lower-priority pages first.
        Priority 1 pages are never evicted.
        """
        tokens = self._estimate_tokens(content)

        # Already loaded? Just refresh access time
        if page_id in self.pages:
            page = self.pages[page_id]
            if page.in_context:
                page.last_accessed = time.monotonic()
                page.access_count += 1
                return page.content

        # Page fault — need to load
        self.page_faults += 1
        while self.in_context_tokens + tokens > self.max_tokens:
            victim = self._select_victim(new_priority=priority)
            if victim is None:
                # Cannot fit even after eviction — truncate
                available = self.max_tokens - self.in_context_tokens
                if available <= 0:
                    return content[:max(100, tokens // 2)]
                content = content[:self._chars_for_tokens(available)]
                tokens = self._estimate_tokens(content)
                break
            self.evict(victim)

        page = ContextPage(
            id=page_id, content=content, tokens=tokens,
            priority=priority, last_accessed=time.monotonic(),
            eviction_policy=eviction_policy, source=source,
        )
        self.pages[page_id] = page
        self.in_context_tokens += tokens
        return content

    def evict(self, page: ContextPage):
        """Evict a page. 类比: page reclaim."""
        if page.eviction_policy == "compress":
            # Compress before evicting — keep a 200-char summary
            summary = page.content[:200] + "…" if len(page.content) > 200 else page.content
            page.content = f"[Compressed] {summary}"
            page.tokens = self._estimate_tokens(page.content)
            page.in_context = False
            self.in_context_tokens -= page.tokens
        else:
            page.in_context = False
            self.in_context_tokens -= page.tokens
        self.evictions += 1
        logger.debug("context_evict", page_id=page.id, policy=page.eviction_policy)

    def unload(self, page_id: str):
        """Explicitly remove a page from context."""
        page = self.pages.pop(page_id, None)
        if page and page.in_context:
            self.in_context_tokens -= page.tokens

    def compress_conversation(self, conversation_text: str, keep_last_n: int = 5) -> str:
        """Compress conversation history. 类比: zswap.

        Older messages get compressed to a summary, recent N kept verbatim.
        """
        lines = conversation_text.strip().split("\n")

        # Simple heuristic: tag lines starting with [Step as "old"
        step_lines = [i for i, ln in enumerate(lines) if ln.startswith("[Step")]
        if len(step_lines) <= keep_last_n:
            return conversation_text

        # Keep last N steps, compress older ones
        cutoff = step_lines[-keep_last_n]
        old = lines[:cutoff]
        recent = lines[cutoff:]

        summary = (
            f"[History Summary: {len(old)} lines compressed] "
            f"Key actions: {self._extract_key_actions(old)}"
        )

        return summary + "\n" + "\n".join(recent)

    def stats(self) -> dict:
        loaded = sum(1 for p in self.pages.values() if p.in_context)
        return {
            "pages_loaded": loaded,
            "total_pages": len(self.pages),
            "tokens_used": self.in_context_tokens,
            "tokens_free": self.max_tokens - self.in_context_tokens,
            "usage_percent": round(self.in_context_tokens / self.max_tokens * 100, 1),
            "page_faults": self.page_faults,
            "evictions": self.evictions,
        }

    def _select_victim(self, new_priority: int) -> ContextPage | None:
        """Select a page to evict. LRU within same priority band.

        Never evict priority 1 pages (system prompt, role).
        Only evict lower-or-equal priority than the new page.
        """
        candidates = [
            p for p in self.pages.values()
            if p.in_context and p.priority > 1 and p.priority >= new_priority
        ]
        if not candidates:
            return None
        # Sort by priority desc (higher = evict first), then by last_accessed asc (older first)
        candidates.sort(key=lambda p: (-p.priority, p.last_accessed))
        return candidates[0]

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token."""
        return max(1, len(text) // 4)

    def _chars_for_tokens(self, tokens: int) -> int:
        return tokens * 4

    def _extract_key_actions(self, lines: list[str]) -> str:
        """Extract tool names from conversation lines for summary."""
        tools = set()
        for line in lines:
            if "Result from" in line:
                tool = line.split("Result from")[1].split(":")[0].strip()
                if "." in tool:
                    tools.add(tool)
        return ", ".join(tools)[:100] if tools else "various actions"
