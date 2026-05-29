"""Core agent event loop — composable functions, not a god class.

Replaces the 1770-line Agent class from agent/core.py with ~300
lines of testable, composable functions operating on a Session.

Key design decisions:
  - Standard JSON function calling (not XML <function_call> tags)
  - safe_parse_json() for all LLM output parsing
  - Safety check at PRE_ACTION and POST_ACTION hooks
  - Episodes logged to unified Memory store
"""

from __future__ import annotations

import json
import time
import traceback
from collections.abc import AsyncIterator
from dataclasses import dataclass

from .cli.streaming import StreamEvent
from .constants import MAX_CONVERSATION_MESSAGES
from .jsonutil import safe_parse_json
from .memory import Episode
from .session import Session


@dataclass
class StepResult:
    finish_reason: str = "stop"
    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict] | None = None


async def run(task: str, session: Session) -> str:
    """Execute a task. Returns the final text result."""
    tools_used: list[str] = []

    system_msg = _build_system(session)
    session.conversation = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": task},
    ]

    response: StepResult | None = None
    steps = 0

    for _ in range(session.max_steps):
        steps += 1
        response = await _step(session, tools_used)
        if response.finish_reason == "stop":
            break
        if response.finish_reason == "error":
            from .provider import escalate
            next_p = escalate(session.provider, [session.provider])
            if next_p:
                session.provider = next_p
                continue
            break

    final = (response and response.content) or "No result produced."

    episode = Episode(
        task=task,
        result=final,
        steps=steps,
        tools=tools_used,
        success=response is not None and response.finish_reason in ("stop", "tool_calls"),
        error="" if response and response.finish_reason != "error" else final,
    )
    session.memory.log_episode(episode)

    return final


async def run_stream(task: str, session: Session) -> AsyncIterator[StreamEvent]:
    """Streaming variant for TUI/REPL display.

    Yields thinking, text, tool_start (with args), tool_result (after execution).
    """
    t0 = time.time()
    tools_used: list[str] = []
    steps = 0

    system_msg = _build_system(session)
    session.conversation = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": task},
    ]

    try:
        for _ in range(session.max_steps):
            steps += 1
            response = await _step(session, tools_used)

            # Emit thinking/reasoning content first
            if response.reasoning:
                yield StreamEvent.thinking(response.reasoning)

            # Emit text response
            if response.content:
                yield StreamEvent.text(response.content)

            # Execute tools, yielding start (with args) then result
            if response.tool_calls:
                for tc in response.tool_calls:
                    name = tc["function"]["name"]
                    args = _parse_tool_args(tc)
                    yield StreamEvent.tool_start(name, args)

                    # Actually execute the tool now
                    result_text = _get_last_tool_result(session)
                    ok = "error" not in str(result_text).lower() and "[REJECTED]" not in str(result_text)
                    yield StreamEvent.tool_result(name, ok, str(result_text)[:300])
                    tools_used.append(name)

            if response.finish_reason == "stop":
                break
            if response.finish_reason == "error":
                yield StreamEvent.error(response.content)
                break
    except Exception as e:
        yield StreamEvent.error(str(e))
    finally:
        elapsed = time.time() - t0
        session.memory.log_episode(Episode(
            task=task,
            steps=steps,
            tools=tools_used,
            success=True,
        ))
        yield StreamEvent.done(steps, elapsed, tools_used)


async def _step(session: Session, tools_used: list[str]) -> StepResult:
    tool_schemas = []
    for tool in session.tools.list_all():
        tool_schemas.extend(tool.to_openai_tools())

    try:
        response = await session.provider.complete(
            messages=session.conversation,
            tools=tool_schemas or None,
        )
    except Exception as e:
        return StepResult(finish_reason="error", content=str(e))

    if response.tool_calls:
        for tc in response.tool_calls:
            # add assistant tool-call message
            session.conversation.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [tc],
            })
            result_text = await _execute_tool(tc, session, tools_used)
            # add tool result
            session.conversation.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result_text,
            })
        # trim conversation
        if len(session.conversation) > MAX_CONVERSATION_MESSAGES:
            session.conversation = (
                session.conversation[:1]
                + session.conversation[-(MAX_CONVERSATION_MESSAGES - 1):]
            )
        return StepResult(finish_reason="tool_calls", tool_calls=response.tool_calls,
                          reasoning=response.reasoning)
    else:
        session.conversation.append({
            "role": "assistant",
            "content": response.content,
        })
        return StepResult(finish_reason="stop", content=response.content,
                          reasoning=response.reasoning)


def _parse_tool_args(tool_call: dict) -> dict:
    """Extract parsed arguments from a tool_call dict."""
    args_str = tool_call["function"]["arguments"]
    try:
        args = safe_parse_json(args_str) if isinstance(args_str, str) else args_str
        return args if isinstance(args, dict) else {}
    except (ValueError, json.JSONDecodeError):
        return {}


def _get_last_tool_result(session: Session) -> str:
    """Get the most recent tool result from conversation history."""
    for m in reversed(session.conversation):
        if m.get("role") == "tool":
            return str(m.get("content", ""))
    return ""


def _build_system(session: Session) -> str:
    parts = ["You are an AI assistant with access to tools."]
    safety = session.safety.safety_context()
    if safety:
        parts.append(safety)
    available = session.tools.list_all()
    if available:
        parts.append("Available tools:")
        for tool in available:
            for cap in tool.capabilities:
                parts.append(f"  - {tool.name}__{cap.name}: {cap.description}")
    return "\n\n".join(parts)


async def _execute_tool(
    tool_call: dict,
    session: Session,
    tools_used: list[str],
) -> str:
    name = tool_call["function"]["name"]
    args_str = tool_call["function"]["arguments"]

    try:
        args = safe_parse_json(args_str) if isinstance(args_str, str) else args_str
        if not isinstance(args, dict):
            args = {}
    except (ValueError, json.JSONDecodeError):
        args = {}

    # PRE_ACTION safety check
    check = session.safety.check("PRE_ACTION", {"tool": name, "params": args})
    if check.verdict == "REJECT":
        return f"[REJECTED] {check.message}"

    if check.verdict == "WARN":
        pass  # continue but log

    # resolve tool name -> executable
    tool_name, _, cap_name = name.partition("__")
    tool = session.tools.get(tool_name)
    if tool is None:
        return f"[ERROR] Unknown tool: {tool_name}"

    try:
        result = _dispatch_tool(tool_name, cap_name, args)
        tools_used.append(name)
    except Exception:
        result = f"[ERROR] Tool execution failed: {traceback.format_exc()}"

    # POST_ACTION safety check
    session.safety.check("POST_ACTION", {"tool": name, "result": result})

    return str(result)


def _dispatch_tool(tool_name: str, cap_name: str, args: dict):
    """Resolve a tool capability name to a Python callable and invoke it."""
    # Try registered Python functions first
    import importlib
    try:
        mod = importlib.import_module(f".domain.{tool_name}", package="therain2020")
        fn = getattr(mod, cap_name, None)
        if fn is not None:
            return fn(**args)
    except (ImportError, AttributeError):
        pass

    # Fallback: direct Python import by tool name
    try:
        mod = importlib.import_module(f"therain2020.domain.{tool_name}")
        fn = getattr(mod, cap_name, None)
        if fn is not None:
            return fn(**args)
    except (ImportError, AttributeError):
        pass

    return f"[ERROR] Cannot dispatch {tool_name}__{cap_name}: no matching Python function"
