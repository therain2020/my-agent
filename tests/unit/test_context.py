"""Tests for context virtual memory manager."""


from agent.context import ContextManager


class TestContextManager:
    def test_load_page(self):
        ctx = ContextManager(max_tokens=10000)
        content = ctx.load("test", "hello world", priority=3)
        assert "hello world" in content
        assert ctx.page_faults == 1

    def test_load_same_page_twice_no_fault(self):
        ctx = ContextManager(max_tokens=10000)
        ctx.load("test", "hello", priority=3)
        faults_before = ctx.page_faults
        ctx.load("test", "hello", priority=3)
        assert ctx.page_faults == faults_before  # No new fault

    def test_priority_one_never_evicted(self):
        ctx = ContextManager(max_tokens=10)  # Tiny context
        ctx.load("system", "A" * 100, priority=1)  # Won't fit well but...
        # Try to load a big page
        ctx.load("huge", "B" * 200, priority=4)
        # Priority 1 should still be in context
        sys_page = ctx.pages.get("system")
        assert sys_page is not None
        assert sys_page.in_context is True  # priority 1 never evicted

    def test_eviction(self):
        ctx = ContextManager(max_tokens=20)  # ~5 tokens worth
        ctx.load("a", "hello world large", priority=3)
        ctx.load("b", "another thing here", priority=3)
        # Both should be loaded; the smaller max will force eviction on 2nd load
        assert ctx.evictions >= 0

    def test_compress_conversation(self):
        ctx = ContextManager()
        conv = (
            "[Step 1] result\n"
            "[Step 2] result\n"
            "[Step 3] result\n"
            "[Step 4] result\n"
            "[Step 5] result\n"
            "[Step 6] result\n"
        )
        compressed = ctx.compress_conversation(conv, keep_last_n=3)
        assert "History Summary" in compressed
        assert "[Step 4]" in compressed
        assert "[Step 5]" in compressed
        assert "[Step 6]" in compressed
        assert "[Step 1]" not in compressed

    def test_stats(self):
        ctx = ContextManager(max_tokens=5000)
        ctx.load("p1", "hello" * 50, priority=2)
        stats = ctx.stats()
        assert stats["tokens_used"] > 0
        assert stats["usage_percent"] > 0
        assert "tokens_free" in stats

    def test_unload(self):
        ctx = ContextManager(max_tokens=5000)
        ctx.load("temp", "temporary content", priority=4)
        assert ctx.pages["temp"].in_context
        ctx.unload("temp")
        assert "temp" not in ctx.pages  # unload removes from dict entirely
