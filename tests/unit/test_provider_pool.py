"""Tests for provider pool and circuit breaker."""


import pytest

from agent.providers.pool import (
    AllProvidersFailed,
    CircuitBreaker,
    CircuitBreakerOpenError,
    ProviderPool,
)


class FakeProvider:
    """Fake provider for testing failover."""

    def __init__(self, name: str, model: str = "fake", should_fail: bool = False):
        self._name = name
        self._model = model
        self.should_fail = should_fail
        self.call_count = 0

    @property
    def name(self):
        return self._name

    @property
    def model(self):
        return self._model

    @property
    def context_window(self):
        return 100000

    def token_count(self, text):
        return len(text) // 4

    async def complete(self, prompt, **kwargs):
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError(f"{self._name} failed")
        from agent.providers import LLMResponse
        return LLMResponse(content=f"response from {self._name}", model=self._model)

    async def complete_stream(self, prompt, **kwargs):
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError(f"{self._name} failed")
        yield f"response from {self._name}"


class TestCircuitBreaker:
    async def test_closed_after_success(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        prov = FakeProvider("ok")
        result = await cb.call(prov.complete, "hello")
        assert result.content == "response from ok"
        assert cb.state == "CLOSED"

    async def test_opens_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        prov = FakeProvider("bad", should_fail=True)

        # 2 failures → breaker opens
        for _ in range(2):
            try:
                await cb.call(prov.complete, "hello")
            except RuntimeError:
                pass

        assert cb.state == "OPEN"

        # Next call should be rejected
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(prov.complete, "hello")


class TestProviderPool:
    async def test_uses_primary(self):
        pool = ProviderPool()
        pool.add(FakeProvider("primary"), {"priority": "primary"})
        result = await pool.complete("test")
        assert "primary" in result.content

    async def test_fallbacks_on_failure(self):
        pool = ProviderPool()
        pool.add(FakeProvider("bad", should_fail=True), {
            "priority": "primary", "failure_threshold": 1, "recovery_timeout": 999,
        })
        pool.add(FakeProvider("fallback"), {"priority": "fallback"})
        result = await pool.complete("test")
        assert "fallback" in result.content

    async def test_all_fail_raises(self):
        pool = ProviderPool()
        pool.add(FakeProvider("bad1", should_fail=True), {
            "priority": "primary", "failure_threshold": 1, "recovery_timeout": 999,
        })
        pool.add(FakeProvider("bad2", should_fail=True), {
            "priority": "fallback", "failure_threshold": 1, "recovery_timeout": 999,
        })
        with pytest.raises(AllProvidersFailed):
            await pool.complete("test")
