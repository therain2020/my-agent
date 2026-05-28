"""Semantic-aware context compression. 类比: zswap + KSM.

Uses a cheap LLM to decide what's safe to compress and how.
Procedural instructions are NEVER compressed — only reference material.
Includes feedback learning to avoid over-compression.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class ContentType(Enum):
    PROCEDURAL = "procedural"       # Instructions, rules — NEVER compress
    REFERENCE = "reference"        # Docs, facts — safe to summarize
    CONVERSATION = "conversation"  # Dialog — keep recent, summarize old
    EVIDENCE = "evidence"          # Tool results — extract key findings


class CompressionDecision(Enum):
    KEEP_INTACT = "keep_intact"
    SUMMARIZE = "summarize"
    TRUNCATE = "truncate"
    DISCARD = "discard"


@dataclass
class CompressionFeedback:
    """Records outcome of a compression decision for learning."""
    content_id: str
    content_type: ContentType
    decision: CompressionDecision
    was_referenced: bool = False
    episode_success: bool = True
    tokens_saved: int = 0


# Procedural markers — if any appear in the first 200 chars, classify as procedural
_PROCEDURAL_MARKERS = (
    "<format_rules", "immutable=", "你必须", "不要", "禁止",
    "先读", "always", "never", "must", "步骤",
    "必须先", "Do NOT", "IMPORTANT", "REQUIRED",
)

# Conversation markers — step/tool result patterns
_CONVERSATION_MARKERS = (
    "[Step", "[Result from", "[Error]", "[Tool",
    "<function_call>", "<action_report>",
)


class SemanticCompressor:
    """LLM-driven semantic compression with feedback learning.

    类比: zswap — compresses pages before swapping.
    KSM — merges semantically similar pages.
    """

    def __init__(self, provider: Any = None, max_compression_tokens: int = 500):
        self.provider = provider  # Cheap model for classification/summarization
        self.max_compression_tokens = max_compression_tokens
        self._feedback: list[CompressionFeedback] = []
        self._bad_patterns: set[str] = set()

    def classify(self, content_id: str, text: str) -> ContentType:
        """Classify content by type. Uses fast heuristics first.

        Fast path covers >90% of cases without LLM cost.
        """
        head = text[:200]

        if any(marker in head for marker in _PROCEDURAL_MARKERS):
            return ContentType.PROCEDURAL

        if any(marker in head for marker in _CONVERSATION_MARKERS):
            return ContentType.CONVERSATION

        if len(text) > 1000 and text.count("\n") > 20:
            return ContentType.CONVERSATION

        return ContentType.REFERENCE

    async def classify_async(self, content_id: str, text: str) -> ContentType:
        """Async classification with LLM fallback for ambiguous content."""
        ct = self.classify(content_id, text)
        if ct != ContentType.REFERENCE or len(text) < 500:
            return ct

        # Ambiguous — use LLM for classification
        if self.provider:
            try:
                prompt = (
                    "Classify this text as one of: PROCEDURAL (instructions/rules), "
                    "REFERENCE (facts/docs), CONVERSATION (dialog), EVIDENCE (results). "
                    "Reply with one word.\n\n"
                    f"Text (first 300 chars): {text[:300]}"
                )
                resp = await self.provider.complete(prompt, max_tokens=10)
                for ctype in ContentType:
                    if ctype.value.upper() in resp.content.upper():
                        return ctype
            except Exception:
                pass

        return ContentType.REFERENCE

    async def compress(
        self,
        content_id: str,
        text: str,
        content_type: ContentType | None = None,
    ) -> tuple[str, CompressionFeedback]:
        """Compress content based on its type."""
        if content_type is None:
            content_type = self.classify(content_id, text)

        decision = self._decide(content_type, text)

        if decision == CompressionDecision.KEEP_INTACT:
            return text, CompressionFeedback(
                content_id=content_id, content_type=content_type,
                decision=decision, tokens_saved=0,
            )

        if decision == CompressionDecision.DISCARD:
            return "", CompressionFeedback(
                content_id=content_id, content_type=content_type,
                decision=decision, tokens_saved=len(text) // 4,
            )

        if decision == CompressionDecision.TRUNCATE:
            truncated = text[:1000] + "\n[...truncated...]"
            return truncated, CompressionFeedback(
                content_id=content_id, content_type=content_type,
                decision=decision, tokens_saved=(len(text) - len(truncated)) // 4,
            )

        # SUMMARIZE — use LLM for smart summarization
        if self.provider:
            try:
                prompt = (
                    "Summarize the following content concisely. "
                    "Keep all key facts, numbers, file paths, function names. "
                    "Discard narrative filler and repetition.\n\n"
                    f"{text[:3000]}"
                )
                resp = await self.provider.complete(
                    prompt, max_tokens=self.max_compression_tokens
                )
                summary = resp.content
                return summary, CompressionFeedback(
                    content_id=content_id, content_type=content_type,
                    decision=decision, tokens_saved=(len(text) - len(summary)) // 4,
                )
            except Exception as e:
                logger.error("compression_llm_failed", error=str(e))

        # Fallback: simple truncation
        truncated = text[:500] + "\n[...truncated...]"
        return truncated, CompressionFeedback(
            content_id=content_id, content_type=content_type,
            decision=CompressionDecision.TRUNCATE,
            tokens_saved=(len(text) - 500) // 4,
        )

    def _decide(self, content_type: ContentType, text: str) -> CompressionDecision:
        """Decide compression strategy based on content type."""
        if content_type == ContentType.PROCEDURAL:
            return CompressionDecision.KEEP_INTACT

        if len(text) < 200:
            return CompressionDecision.KEEP_INTACT

        if content_type == ContentType.EVIDENCE:
            if len(text) > 2000:
                return CompressionDecision.SUMMARIZE
            return CompressionDecision.KEEP_INTACT

        if content_type == ContentType.CONVERSATION:
            if len(text) > 3000:
                return CompressionDecision.SUMMARIZE
            return CompressionDecision.TRUNCATE

        if content_type == ContentType.REFERENCE:
            if len(text) > 1000:
                return CompressionDecision.SUMMARIZE
            return CompressionDecision.KEEP_INTACT

        return CompressionDecision.KEEP_INTACT

    def record_feedback(self, content_id: str, was_referenced: bool,
                        episode_success: bool) -> None:
        """Record whether compressed content was later needed.

        If compressed content was referenced but unavailable → compression
        was too aggressive → adjust future decisions.
        """
        for fb in self._feedback:
            if fb.content_id == content_id:
                fb.was_referenced = was_referenced
                fb.episode_success = episode_success

                if was_referenced and not episode_success:
                    pattern = content_id.split(":")[0] if ":" in content_id else content_id
                    self._bad_patterns.add(pattern)
                    logger.warning(
                        "compression_caused_failure",
                        content_id=content_id,
                        pattern=pattern,
                    )
                break

    @property
    def stats(self) -> dict:
        total_saved = sum(fb.tokens_saved for fb in self._feedback)
        over_compressed = sum(
            1 for fb in self._feedback
            if fb.was_referenced and not fb.episode_success
        )
        return {
            "total_compressions": len(self._feedback),
            "total_tokens_saved": total_saved,
            "over_compressions": over_compressed,
            "bad_patterns": len(self._bad_patterns),
        }
