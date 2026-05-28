"""Tests for session.py — session creation and wiring."""

import pytest

from therain2020.session import Session, create_session


def test_create_session_requires_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No LLM provider"):
        create_session(task="hello")


def test_create_session_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    session = create_session(task="hello", workspace=tmp_path, memory_path=":memory:")
    assert session.provider is not None
    assert session.memory is not None
    assert session.tools is not None
    assert session.safety is not None
    assert session.workspace == tmp_path


def test_session_dataclass():
    from therain2020.memory import Memory
    from therain2020.provider import LLMProvider
    from therain2020.safety import SafetyEngine
    from therain2020.tools import ToolRegistry

    mem = Memory(":memory:")
    tools = ToolRegistry()
    safety = SafetyEngine()
    provider = LLMProvider("test", "model")

    session = Session(
        memory=mem,
        tools=tools,
        safety=safety,
        provider=provider,
    )
    assert session.max_steps == 5
    session.memory.close()
