"""Structured streaming events for real-time REPL display.

Claude Code uses an AsyncGenerator yielding typed messages.
We use the same pattern: StreamEvent types for thinking, text, tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StreamEventType(Enum):
    THINKING = "thinking"           # Model reasoning content (expandable)
    TEXT = "text"                   # Visible response text
    TOOL_START = "tool_start"       # Tool call starting
    TOOL_RESULT = "tool_result"     # Tool call completed
    ERROR = "error"                 # Error occurred
    DONE = "done"                   # Task complete


@dataclass
class StreamEvent:
    """A single streaming event sent to the display layer.

    Analogous to Claude Code's yield values from query().
    """

    type: StreamEventType
    content: str = ""               # Text or thinking content
    tool_name: str = ""             # For TOOL_START / TOOL_RESULT
    capability: str = ""
    ok: bool = True                 # For TOOL_RESULT
    steps: int = 0                  # For DONE
    duration: float = 0.0           # For DONE
    success: bool = False           # For DONE
    error_msg: str = ""             # For ERROR or DONE
    tools_used: list[str] = field(default_factory=list)

    @classmethod
    def thinking(cls, content: str) -> StreamEvent:
        return cls(type=StreamEventType.THINKING, content=content)

    @classmethod
    def text(cls, content: str) -> StreamEvent:
        return cls(type=StreamEventType.TEXT, content=content)

    @classmethod
    def tool_start(cls, name: str, cap: str) -> StreamEvent:
        return cls(type=StreamEventType.TOOL_START, tool_name=name, capability=cap)

    @classmethod
    def tool_result(cls, name: str, cap: str, ok: bool = True) -> StreamEvent:
        return cls(type=StreamEventType.TOOL_RESULT, tool_name=name, capability=cap, ok=ok)

    @classmethod
    def error(cls, message: str) -> StreamEvent:
        return cls(type=StreamEventType.ERROR, content=message)

    @classmethod
    def done(cls, success: bool, steps: int, duration: float,
             tools: list[str], error: str = "") -> StreamEvent:
        return cls(
            type=StreamEventType.DONE,
            success=success, steps=steps, duration=duration,
            tools_used=tools, error_msg=error,
        )
