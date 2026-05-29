"""Tests for provider.py — get_configured_provider and routing."""

import pytest

from therain2020.provider import (
    LLMProvider,
    TaskComplexity,
    estimate_complexity,
    get_configured_provider,
    route,
)


class TestEstimateComplexity:
    def test_simple_keywords(self):
        assert estimate_complexity("read the file") == TaskComplexity.SIMPLE
        assert estimate_complexity("list all files") == TaskComplexity.SIMPLE

    def test_complex_keywords(self):
        assert estimate_complexity("refactor the auth module") == TaskComplexity.COMPLEX

    def test_moderate_default(self):
        assert estimate_complexity("implement a new feature") == TaskComplexity.MODERATE


class TestRouting:
    @pytest.fixture
    def providers(self):
        return [
            LLMProvider("cheap", "cheap-model", cost_per_1k=0.1),
            LLMProvider("strong", "strong-model", cost_per_1k=5.0),
        ]

    def test_simple_routes_to_cheapest(self, providers):
        p = route("list files", providers)
        assert p.name == "cheap"

    def test_complex_routes_to_strongest(self, providers):
        p = route("refactor the auth system", providers)
        assert p.name == "strong"

    def test_empty_providers_raises(self):
        with pytest.raises(RuntimeError):
            route("task", [])


class TestGetConfiguredProvider:
    def test_returns_none_for_empty_config(self):
        assert get_configured_provider(config={}) is None

    def test_returns_none_when_no_active_provider(self):
        config = {"provider": None, "providers": {}}
        assert get_configured_provider(config=config) is None

    def test_returns_none_when_no_api_key(self):
        config = {"provider": "qwen", "providers": {"qwen": {}}}
        assert get_configured_provider(config=config) is None

    def test_reads_from_config(self):
        config = {
            "provider": "qwen",
            "providers": {
                "qwen": {
                    "api_key": "sk-test",
                    "model": "qwen-plus",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                },
            },
        }
        p = get_configured_provider(config=config)
        assert p is not None
        assert p.name == "qwen"
        assert p.model == "qwen-plus"
        assert p._api_key == "sk-test"
        assert p._base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_falls_back_to_registry_defaults(self):
        config = {
            "provider": "qwen",
            "providers": {"qwen": {"api_key": "sk-test"}},
        }
        p = get_configured_provider(config=config)
        assert p is not None
        assert p.name == "qwen"
        assert p._api_key == "sk-test"
        assert p.model == "qwen-plus"  # from registry
        assert p._base_url is not None  # from registry


class TestLLMProvider:
    def test_token_count(self):
        p = LLMProvider("test", "test-model")
        assert p.token_count("hello world") >= 1
        assert p.token_count("你好世界") >= 1

    def test_proxy_url_no_scheme(self, monkeypatch):
        from therain2020.provider import _proxy_url
        monkeypatch.setenv("net_proxy", "127.0.0.1:7890")
        assert _proxy_url() == "http://127.0.0.1:7890"

    def test_proxy_url_with_scheme(self, monkeypatch):
        from therain2020.provider import _proxy_url
        monkeypatch.setenv("net_proxy", "http://127.0.0.1:7890")
        assert _proxy_url() == "http://127.0.0.1:7890"

    def test_proxy_url_none(self, monkeypatch):
        from therain2020.provider import _proxy_url
        monkeypatch.delenv("net_proxy", raising=False)
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        assert _proxy_url() is None
