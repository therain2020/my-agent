"""Tests for provider auto-detection from environment variables."""


from agent.cli.autodetect import _KNOWN_PROVIDERS, detect_all_from_env, detect_from_env


class TestEnvProvider:
    def test_known_providers_have_required_fields(self):
        for ep in _KNOWN_PROVIDERS:
            assert ep.name
            assert ep.adapter
            assert ep.key_env

    def test_deepseek_is_first(self):
        assert _KNOWN_PROVIDERS[0].name == "deepseek"

    def test_at_least_five_providers(self):
        assert len(_KNOWN_PROVIDERS) >= 5


class TestDetectFromEnv:
    def test_nothing_when_no_keys_set(self, monkeypatch):
        for ep in _KNOWN_PROVIDERS:
            monkeypatch.delenv(ep.key_env, raising=False)
        provider, config, source = detect_from_env()
        assert provider is None

    def test_detects_deepseek(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek-key")
        provider, config, source = detect_from_env()
        assert provider is not None
        assert "deepseek" in source
        assert "DEEPSEEK_API_KEY" in source

    def test_detects_anthropic(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        # Clear deepseek so anthropic is first found
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        provider, config, source = detect_from_env()
        assert provider is not None
        assert "anthropic" in source

    def test_detects_openai(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-key")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        provider, config, source = detect_from_env()
        assert provider is not None
        assert "openai" in source


class TestDetectAll:
    def test_returns_empty_when_none_set(self, monkeypatch):
        for ep in _KNOWN_PROVIDERS:
            monkeypatch.delenv(ep.key_env, raising=False)
        results = detect_all_from_env()
        assert results == []

    def test_returns_multiple_when_available(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        results = detect_all_from_env()
        assert len(results) >= 2
