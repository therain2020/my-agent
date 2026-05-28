"""Tests for provider.py — LLM provider detection and routing."""

import pytest

from therain2020.provider import (
    LLMProvider,
    TaskComplexity,
    detect_providers,
    escalate,
    estimate_complexity,
    route,
)


class TestEstimateComplexity:
    def test_simple_keywords(self):
        assert estimate_complexity("read the file") == TaskComplexity.SIMPLE
        assert estimate_complexity("list all files") == TaskComplexity.SIMPLE
        assert estimate_complexity("show me the code") == TaskComplexity.SIMPLE
        assert estimate_complexity("find all python files") == TaskComplexity.SIMPLE

    def test_complex_keywords(self):
        assert estimate_complexity("refactor the auth module") == TaskComplexity.COMPLEX
        assert estimate_complexity("design a new architecture") == TaskComplexity.COMPLEX
        assert estimate_complexity("debug the memory leak") == TaskComplexity.COMPLEX
        assert estimate_complexity("fix the race condition") == TaskComplexity.COMPLEX

    def test_moderate_default(self):
        assert estimate_complexity("implement a new feature") == TaskComplexity.MODERATE
        assert estimate_complexity("update the config") == TaskComplexity.MODERATE
        assert estimate_complexity("create a test file") == TaskComplexity.MODERATE


class TestRouting:
    @pytest.fixture
    def providers(self):
        return [
            LLMProvider("cheap", "cheap-model", cost_per_1k=0.1),
            LLMProvider("mid", "mid-model", cost_per_1k=1.0),
            LLMProvider("strong", "strong-model", cost_per_1k=5.0),
        ]

    def test_simple_routes_to_cheapest(self, providers):
        p = route("list files", providers)
        assert p.name == "cheap"

    def test_complex_routes_to_strongest(self, providers):
        p = route("refactor the auth system", providers)
        assert p.name == "strong"

    def test_moderate_routes_to_middle(self, providers):
        p = route("implement feature x", providers)
        assert p.name == "mid"

    def test_single_provider(self):
        providers = [LLMProvider("only", "model")]
        p = route("do anything", providers)
        assert p.name == "only"

    def test_empty_providers_raises(self):
        with pytest.raises(RuntimeError):
            route("task", [])


class TestEscalate:
    @pytest.fixture
    def providers(self):
        return [
            LLMProvider("a", "a", cost_per_1k=0.1),
            LLMProvider("b", "b", cost_per_1k=1.0),
            LLMProvider("c", "c", cost_per_1k=5.0),
        ]

    def test_escalate_from_cheapest(self, providers):
        next_p = escalate(providers[0], providers)
        assert next_p is not None
        assert next_p.name == "b"

    def test_escalate_from_top_returns_none(self, providers):
        next_p = escalate(providers[-1], providers)
        assert next_p is None


class TestDetectProviders:
    def test_no_env_vars_returns_empty(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        providers = detect_providers()
        assert len(providers) == 0

    def test_openai_detected(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        providers = detect_providers()
        names = [p.name for p in providers]
        assert "openai-mini" in names
        assert "openai-large" in names

    def test_deepseek_detected(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        providers = detect_providers()
        assert len(providers) == 1
        assert providers[0].name == "deepseek"

    def test_sorted_by_cost(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        providers = detect_providers()
        costs = [p.cost_per_1k for p in providers]
        assert costs == sorted(costs)


class TestLLMProvider:
    def test_token_count(self):
        p = LLMProvider("test", "test-model")
        assert p.token_count("hello world") >= 1
        assert p.token_count("你好世界") >= 1
