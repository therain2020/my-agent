"""Claude Code-style REPL — ⏺ prompt, ⎿ response, ● tools, ✓ results.

Zero external deps. Pure ANSI escape codes.
"""

from __future__ import annotations

import asyncio
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from dataclasses import dataclass, field
from enum import Enum

# -- ANSI escapes ---------------------------------------------------------

HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
GRAY = "\x1b[90m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
CLEAR_LINE = "\x1b[2K\r"


# -- event types ----------------------------------------------------------

class EventType(Enum):
    THINKING = "thinking"
    TEXT = "text"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    DONE = "done"


@dataclass
class Event:
    type: EventType
    content: str = ""
    tool_name: str = ""
    arguments: dict = field(default_factory=dict)
    ok: bool = False
    steps: int = 0
    duration: float = 0.0
    tokens: int = 0
    tools_used: list[str] = field(default_factory=list)

    @classmethod
    def thinking(cls, text: str):
        return cls(EventType.THINKING, content=text)
    @classmethod
    def text(cls, text: str):
        return cls(EventType.TEXT, content=text)
    @classmethod
    def tool_start(cls, name: str, args: dict):
        return cls(EventType.TOOL_START, tool_name=name, arguments=args)
    @classmethod
    def tool_result(cls, name: str, ok: bool, text: str = ""):
        return cls(EventType.TOOL_RESULT, tool_name=name, ok=ok, content=text)
    @classmethod
    def error(cls, msg: str):
        return cls(EventType.ERROR, content=msg)
    @classmethod
    def done(cls, steps: int, duration: float, tools: list[str], tokens: int = 0) -> Event:
        return cls(EventType.DONE, steps=steps, duration=duration, tools_used=tools, tokens=tokens)


# -- REPL -----------------------------------------------------------------

class Repl:
    def __init__(self):
        self.turn: int = 0
        self._running: bool = False
        self._thinking_visible: bool = False  # Ctrl+O toggles
        self._pending_thinking: str = ""
        self._model: str = ""

    async def start(self):
        self._running = True
        sys.stdout.write(HIDE_CURSOR)
        try:
            print()
            while self._running:
                try:
                    line = await self._prompt()
                    if line is None:
                        break
                    line = line.strip()
                    if line.startswith("/"):
                        self._handle_slash(line)
                    elif line:
                        await self._execute(line)
                except EOFError:
                    break
                except KeyboardInterrupt:
                    print()
                    continue
                except Exception as e:
                    print(f"\n  {RED}Error: {e}{RESET}\n")
        finally:
            sys.stdout.write(SHOW_CURSOR)
            print()

    async def _prompt(self) -> str | None:
        sys.stdout.write(f"{GREEN}⏺ {RESET}")
        sys.stdout.flush()
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, input)
        except (asyncio.CancelledError, KeyboardInterrupt):
            return None  # Ctrl+C
        except RuntimeError:
            return await loop.run_in_executor(None, sys.stdin.readline)

    async def _execute(self, task: str):
        from ..agent import run_stream
        from ..session import create_session

        self.turn += 1
        t0 = time.time()
        steps = 0
        tokens = 0

        try:
            session = create_session(task=task)
            self._model = session.provider.model
            self._pending_thinking = ""
            _thinking_shown = False

            # Show waiting indicator during LLM call
            sys.stdout.write(f"  {DIM}···{RESET}")
            sys.stdout.flush()
            _first = True

            async for event in run_stream(task, session):
                if _first:
                    _first = False
                    sys.stdout.write(CLEAR_LINE)
                    sys.stdout.flush()

                if event.type == EventType.THINKING:
                    if self._thinking_visible:
                        if not _thinking_shown:
                            print()
                        for line in event.content.strip().split("\n")[:8]:
                            print(f"  {DIM}{line}{RESET}", flush=True)
                        _thinking_shown = True
                    else:
                        self._pending_thinking += event.content

                elif event.type == EventType.TEXT:
                    _thinking_shown = False
                    if self._pending_thinking:
                        print(f"  {DIM}⋯ (thinking · {GRAY}/think{RESET}{DIM} to expand){RESET}")
                        self._pending_thinking = ""
                    for line in event.content.strip().split("\n"):
                        print(f"\n  {GRAY}⎿{RESET}  {line}", flush=True)

                elif event.type == EventType.TOOL_START:
                    # Flush pending thinking before first tool of a step
                    if self._pending_thinking:
                        print(f"  {DIM}⋯ (thinking · {GRAY}/think{RESET}{DIM} to expand){RESET}")
                        self._pending_thinking = ""
                    _thinking_shown = False
                    args = event.arguments
                    args_str = ", ".join(
                        f"{k}={_trunc(repr(v), 80)}" for k, v in args.items()
                    )
                    print(f"\n  {YELLOW}●{RESET} {event.tool_name}({args_str})", flush=True)

                elif event.type == EventType.TOOL_RESULT:
                    mark = f"{GREEN}●{RESET}" if event.ok else f"{RED}●{RESET}"
                    text = event.content or ""
                    if not text:
                        pass  # no output
                    elif len(text) < 80:
                        print(f"  {mark} {text}", flush=True)
                    else:
                        print(f"  {mark} ({len(text)} chars)", flush=True)

                elif event.type == EventType.ERROR:
                    print(f"\n  {RED}Error: {event.content[:300]}{RESET}", flush=True)

                elif event.type == EventType.DONE:
                    steps = event.steps
                    tokens = event.tokens

            elapsed = time.time() - t0
            _status_bar(self._model, steps, tokens, elapsed)
            session.memory.close()

        except Exception as e:
            elapsed = time.time() - t0
            _status_bar(self._model, steps, tokens, elapsed)
            print(f"\n  {RED}Error: {e}{RESET}\n")

    def _handle_slash(self, cmd: str):
        parts = cmd.split()
        op = parts[0].lower()
        if op in ("/exit", "/quit"):
            self._running = False
        elif op == "/help":
            print(f"  {GRAY}Commands:{RESET} /help /tools /clear /exit /think")
        elif op == "/tools":
            from ..session import create_session
            try:
                session = create_session(task="")
                for t in session.tools.list_all():
                    caps = ", ".join(c.name for c in t.capabilities)
                    print(f"  {YELLOW}{t.name}{RESET} — {caps}")
                session.memory.close()
            except Exception as e:
                print(f"  {RED}{e}{RESET}")
        elif op == "/think":
            self._thinking_visible = not self._thinking_visible
            state = "visible" if self._thinking_visible else "collapsed"
            print(f"  {GRAY}Thinking {state}{RESET}")
        elif op == "/clear":
            sys.stdout.write("\x1b[2J\x1b[H")
        else:
            print(f"  {GRAY}Unknown: {op}{RESET}")


# -- helpers --------------------------------------------------------------

def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 3] + "..."


def _status_bar(model: str, steps: int, tokens: int, elapsed: float):
    bar = "─" * 50
    info = f"{model} · {steps} steps"
    print(f"{GRAY}{bar}{RESET}")
    print(f"  {GRAY}{info} · {elapsed:.1f}s{RESET}\n")
