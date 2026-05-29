"""Streaming event types for TUI and REPL display.

Kept in a separate module so cli/ modules don't depend on agent.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StreamEventType(Enum):
    THINKING = "thinking"
    TEXT = "text"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    DONE = "done"


@dataclass
class StreamEvent:
    type: StreamEventType
    content: str = ""
    arguments: dict = field(default_factory=dict)
    tool_name: str = ""
    capability: str = ""
    ok: bool = False
    steps: int = 0
    duration: float = 0.0
    success: bool = False
    error_msg: str = ""
    tools_used: list[str] = field(default_factory=list)

    @classmethod
    def thinking(cls, content: str) -> StreamEvent:
        return cls(type=StreamEventType.THINKING, content=content)

    @classmethod
    def text(cls, content: str) -> StreamEvent:
        return cls(type=StreamEventType.TEXT, content=content)

    @classmethod
    def tool_start(cls, name: str, args: dict | None = None) -> StreamEvent:
        return cls(type=StreamEventType.TOOL_START, tool_name=name,
                   arguments=args or {})

    @classmethod
    def tool_result(cls, name: str, ok: bool, content: str = "") -> StreamEvent:
        return cls(type=StreamEventType.TOOL_RESULT, tool_name=name, ok=ok,
                   content=content)

    @classmethod
    def error(cls, msg: str) -> StreamEvent:
        return cls(type=StreamEventType.ERROR, error_msg=msg, content=msg)

    @classmethod
    def done(cls, steps: int, duration: float, tools_used: list[str], success: bool = True) -> StreamEvent:
        return cls(type=StreamEventType.DONE, steps=steps, duration=duration, tools_used=tools_used, success=success)
