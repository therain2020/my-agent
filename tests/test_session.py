"""Tests for session.py — session creation from config."""

import pytest

from therain2020.session import Session, create_session


def test_create_session_requires_provider(monkeypatch, tmp_path):
    monkeypatch.setattr("therain2020.config.CONFIG_PATH", tmp_path / "nonexistent.yaml")
    with pytest.raises(RuntimeError, match="No LLM provider"):
        create_session(task="hello", config={}, interactive=False)


def test_create_session_from_config():
    config = {
        "provider": "deepseek",
        "providers": {
            "deepseek": {
                "api_key": "sk-test",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
            },
        },
    }
    session = create_session(task="hello", config=config, interactive=False)
    assert session.provider.name == "deepseek"
    assert session.provider._api_key == "sk-test"
    session.memory.close()


def test_session_dataclass():
    from therain2020.memory import Memory
    from therain2020.provider import LLMProvider
    from therain2020.safety import SafetyEngine
    from therain2020.tools import ToolRegistry

    mem = Memory(":memory:")
    tools = ToolRegistry()
    safety = SafetyEngine()
    provider = LLMProvider("test", "model", api_key="sk-test")

    session = Session(
        memory=mem,
        tools=tools,
        safety=safety,
        provider=provider,
    )
    assert session.max_steps == 5
    session.memory.close()
