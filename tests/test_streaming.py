"""Tests for cli/streaming.py — StreamEvent types."""

from therain2020.cli.streaming import StreamEvent, StreamEventType


def test_thinking_event():
    e = StreamEvent.thinking("reasoning...")
    assert e.type == StreamEventType.THINKING
    assert e.content == "reasoning..."


def test_text_event():
    e = StreamEvent.text("hello")
    assert e.type == StreamEventType.TEXT
    assert e.content == "hello"


def test_tool_start_event():
    e = StreamEvent.tool_start("read_file", "read")
    assert e.type == StreamEventType.TOOL_START
    assert e.tool_name == "read_file"
    assert e.capability == "read"


def test_tool_result_event():
    e = StreamEvent.tool_result("read_file", True, "content")
    assert e.type == StreamEventType.TOOL_RESULT
    assert e.ok is True


def test_tool_result_fail():
    e = StreamEvent.tool_result("bad_tool", False)
    assert e.type == StreamEventType.TOOL_RESULT
    assert e.ok is False


def test_error_event():
    e = StreamEvent.error("something went wrong")
    assert e.type == StreamEventType.ERROR
    assert "wrong" in e.error_msg


def test_done_event():
    e = StreamEvent.done(steps=3, duration=1.5, tools_used=["a", "b"])
    assert e.type == StreamEventType.DONE
    assert e.steps == 3
    assert e.tools_used == ["a", "b"]
    assert e.success is True
