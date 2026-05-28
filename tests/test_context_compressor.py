"""Tests for semantic-aware context compression (十一-C)."""

from agent.context_compressor import (
    CompressionDecision,
    CompressionFeedback,
    ContentType,
    SemanticCompressor,
)


class TestContentType:
    def test_procedural_markers(self):
        compressor = SemanticCompressor()
        assert compressor.classify("p1", "<format_rules immutable=\"true\">") == ContentType.PROCEDURAL
        assert compressor.classify("p2", "你必须 先读 这个文件") == ContentType.PROCEDURAL
        assert compressor.classify("p3", "Do NOT compress this section") == ContentType.PROCEDURAL

    def test_conversation_markers(self):
        compressor = SemanticCompressor()
        assert compressor.classify("c1", "[Step 1] Agent called tool...") == ContentType.CONVERSATION
        assert compressor.classify("c2", "[Result from file-system.read]: foo") == ContentType.CONVERSATION
        assert compressor.classify("c3", "<function_call>\n<name>test</name>") == ContentType.CONVERSATION

    def test_reference_default(self):
        compressor = SemanticCompressor()
        assert compressor.classify("r1", "This is a documentation page about...") == ContentType.REFERENCE

    def test_long_text_defaults_to_conversation(self):
        compressor = SemanticCompressor()
        long_text = "line with more content here\n" * 50
        assert compressor.classify("long", long_text) == ContentType.CONVERSATION


class TestCompressionDecision:
    def test_procedural_never_compressed(self):
        compressor = SemanticCompressor()
        decision = compressor._decide(ContentType.PROCEDURAL, "x" * 500)
        assert decision == CompressionDecision.KEEP_INTACT

    def test_short_text_kept(self):
        compressor = SemanticCompressor()
        decision = compressor._decide(ContentType.REFERENCE, "short")
        assert decision == CompressionDecision.KEEP_INTACT

    def test_large_reference_summarized(self):
        compressor = SemanticCompressor()
        decision = compressor._decide(ContentType.REFERENCE, "x" * 2000)
        assert decision == CompressionDecision.SUMMARIZE

    def test_large_conversation_summarized(self):
        compressor = SemanticCompressor()
        decision = compressor._decide(ContentType.CONVERSATION, "x" * 4000)
        assert decision == CompressionDecision.SUMMARIZE

    def test_medium_conversation_truncated(self):
        compressor = SemanticCompressor()
        decision = compressor._decide(ContentType.CONVERSATION, "x" * 500)
        assert decision == CompressionDecision.TRUNCATE


class TestCompressionFeedback:
    def test_record_feedback(self):
        compressor = SemanticCompressor()
        fb = CompressionFeedback(
            content_id="test:123",
            content_type=ContentType.REFERENCE,
            decision=CompressionDecision.SUMMARIZE,
            tokens_saved=100,
        )
        compressor._feedback.append(fb)
        compressor.record_feedback("test:123", was_referenced=True, episode_success=False)
        assert "test" in compressor._bad_patterns

    def test_stats(self):
        compressor = SemanticCompressor()
        compressor._feedback.append(CompressionFeedback(
            content_id="a", content_type=ContentType.REFERENCE,
            decision=CompressionDecision.SUMMARIZE, tokens_saved=50,
        ))
        stats = compressor.stats
        assert stats["total_compressions"] == 1
        assert stats["total_tokens_saved"] == 50


class TestSyncCompress:
    def test_procedural_not_modified(self):
        compressor = SemanticCompressor()
        text = "<format_rules immutable=\"true\">\nNever change this.\n</format_rules>"
        ct = compressor.classify("test", text)
        decision = compressor._decide(ct, text)
        assert decision == CompressionDecision.KEEP_INTACT

    def test_short_text_not_compressed(self):
        compressor = SemanticCompressor()
        decision = compressor._decide(ContentType.REFERENCE, "hi")
        assert decision == CompressionDecision.KEEP_INTACT
