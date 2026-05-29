"""Tests for cli/app.py — Event types."""

from therain2020.cli.app import Event, EventType


def test_thinking_event():
    e = Event.thinking("reasoning...")
    assert e.type == EventType.THINKING
    assert e.content == "reasoning..."


def test_text_event():
    e = Event.text("hello")
    assert e.type == EventType.TEXT


def test_tool_start_event():
    e = Event.tool_start("bash", {"command": "ls"})
    assert e.type == EventType.TOOL_START
    assert e.arguments == {"command": "ls"}


def test_tool_result_event():
    e = Event.tool_result("bash", True, "done")
    assert e.type == EventType.TOOL_RESULT
    assert e.ok is True


def test_error_event():
    e = Event.error("fail")
    assert e.type == EventType.ERROR


def test_done_event():
    e = Event.done(steps=3, duration=1.5, tools=["a", "b"], tokens=100)
    assert e.steps == 3
    assert e.tokens == 100
