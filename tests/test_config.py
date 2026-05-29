"""Tests for config.py — config persistence and provider registry."""

from therain2020.config import (
    PROVIDER_REGISTRY,
    get_api_key,
    load_config,
    save_config,
)


def test_load_default_config(tmp_path, monkeypatch):
    monkeypatch.setattr("therain2020.config.CONFIG_PATH", tmp_path / "nonexistent.yaml")
    config = load_config()
    assert "provider" in config
    assert "providers" in config
    assert config["provider"] is None


def test_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr("therain2020.config.CONFIG_PATH", tmp_path / "config.yaml")
    config = load_config()
    config["provider"] = "deepseek"
    save_config(config)
    loaded = load_config()
    assert loaded["provider"] == "deepseek"


def test_get_api_key_from_config(tmp_path, monkeypatch):
    monkeypatch.setattr("therain2020.config.CONFIG_PATH", tmp_path / "config.yaml")
    config = load_config()
    config.setdefault("providers", {})["deepseek"] = {"api_key": "sk-config-key"}
    save_config(config)
    key = get_api_key("deepseek", load_config())
    assert key == "sk-config-key"


def test_get_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key")
    key = get_api_key("deepseek", {})
    assert key == "sk-env-key"


def test_env_priority_over_config(tmp_path, monkeypatch):
    monkeypatch.setattr("therain2020.config.CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key")
    config = load_config()
    config.setdefault("providers", {})["deepseek"] = {"api_key": "sk-file-key"}
    save_config(config)
    key = get_api_key("deepseek", load_config())
    assert key == "sk-env-key"  # env wins


def test_provider_registry_has_all_majors():
    names = {r[0] for r in PROVIDER_REGISTRY}
    assert "openai" in names
    assert "anthropic" in names
    assert "deepseek" in names
    assert "gemini" in names
    assert "groq" in names
    assert "mistral" in names
