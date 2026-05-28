"""Tests for agent.py — core event loop with mock provider."""

import asyncio

from therain2020.agent import _build_system, run
from therain2020.memory import Memory
from therain2020.provider import LLMResponse
from therain2020.safety import SafetyEngine
from therain2020.session import Session
from therain2020.tools import ToolRegistry
from therain2020.tools_md import parse_tool_md

SAMPLE_TOOL = """---
name: echo
version: 1.0.0
objects: []
capabilities:
  - name: echo
    description: Echo back the message
    parameters:
      message: string (required) — The message to echo
---
"""


class _MockProvider:
    """Simulates LLMProvider with controlled responses."""

    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.calls: list[dict] = []
        self.name = "mock"
        self.model = "mock-model"
        self.cost_per_1k = 0.0

    async def complete(self, messages, tools=None, tool_choice="auto", max_tokens=4096):
        self.calls.append({"messages": messages, "tools": tools})
        if self.calls:
            return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        return LLMResponse(content="done")


def make_session():
    mem = Memory(":memory:")
    tools = ToolRegistry()
    tools.register(parse_tool_md(SAMPLE_TOOL))
    safety = SafetyEngine()
    provider = _MockProvider([])
    return Session(
        memory=mem,
        tools=tools,
        safety=safety,
        provider=provider,
    )


class TestAgentRun:
    def test_simple_text_response(self):
        session = make_session()
        session.provider = _MockProvider([
            LLMResponse(content="Hello, world!", finish_reason="stop"),
        ])
        result = asyncio.run(run("say hello", session))
        assert "hello" in result.lower()

    def test_tool_call_flow(self):
        session = make_session()
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "echo__echo", "arguments": '{"message": "test"}'},
        }
        session.provider = _MockProvider([
            LLMResponse(content="", tool_calls=[tool_call], finish_reason="tool_calls"),
            LLMResponse(content="The echo worked.", finish_reason="stop"),
        ])
        result = asyncio.run(run("echo test", session))
        assert "echo worked" in result.lower()

    def test_episode_logged(self):
        session = make_session()
        session.provider = _MockProvider([
            LLMResponse(content="Done.", finish_reason="stop"),
        ])
        asyncio.run(run("do thing", session))
        recent = session.memory.get_recent(10)
        assert len(recent) == 1
        assert recent[0].task == "do thing"
        session.memory.close()

    def test_tools_listed_in_system(self):
        session = make_session()
        sys_msg = _build_system(session)
        assert "echo" in sys_msg
        session.memory.close()
