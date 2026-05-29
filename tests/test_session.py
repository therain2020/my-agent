"""Tests for session.py — session creation and wiring."""

import pytest

from therain2020.session import Session, create_session


def test_create_session_requires_provider(monkeypatch, tmp_path):
    for ev in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
               "GEMINI_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY",
               "DASHSCOPE_API_KEY", "ALI_TONGYI_KEY", "ARK_API_KEY",
               "ZHIPUAI_API_KEY", "MOONSHOT_API_KEY", "QIANFAN_ACCESS_KEY"):
        monkeypatch.delenv(ev, raising=False)
    monkeypatch.setattr("therain2020.config.CONFIG_PATH", tmp_path / "nonexistent.yaml")
    with pytest.raises(RuntimeError, match="No LLM provider"):
        create_session(task="hello", config={}, interactive=False)
        create_session(task="hello")


def test_create_session_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    for ev in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DASHSCOPE_API_KEY",
               "ALI_TONGYI_KEY", "ARK_API_KEY", "ZHIPUAI_API_KEY"):
        monkeypatch.delenv(ev, raising=False)
    session = create_session(task="hello", workspace=tmp_path, memory_path=":memory:", interactive=False)
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
