"""Claude Code-style REPL — async start(), no nested asyncio.run()."""

from __future__ import annotations

import asyncio
import sys
import time

from ..agent import run_stream
from ..cli.streaming import StreamEventType
from ..session import create_session


class AgentRepl:
    def __init__(self):
        self.turn: int = 0
        self._running: bool = False

    async def start(self):
        self._running = True
        print("therain2020 REPL — type /help for commands, /exit to quit")
        print()

        while self._running:
            try:
                text = await self._prompt()
                if text is None:
                    break
                text = text.strip()
                if text.startswith("/"):
                    self._handle_slash(text)
                elif text:
                    await self._execute(text)
            except (EOFError, KeyboardInterrupt):
                break
            except Exception as e:
                print(f"\nError: {e}\n")

        print("\nBye.")

    async def _prompt(self) -> str | None:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, lambda: input("> "))
        except RuntimeError:
            return await loop.run_in_executor(None, sys.stdin.readline)

    async def _execute(self, task: str):
        self.turn += 1
        t0 = time.time()
        steps = 0
        _first_event = True

        try:
            session = create_session(task=task)
            print()

            # Show waiting indicator during LLM call
            sys.stdout.write("  …")
            sys.stdout.flush()

            async for event in run_stream(task, session):
                if _first_event:
                    _first_event = False
                    sys.stdout.write("\r")  # clear the "…"
                    sys.stdout.flush()

                if event.type == StreamEventType.THINKING:
                    self._show_thinking(event.content)
                elif event.type == StreamEventType.TEXT:
                    print(event.content, end="", flush=True)
                elif event.type == StreamEventType.TOOL_START:
                    self._show_tool_start(event)
                elif event.type == StreamEventType.TOOL_RESULT:
                    self._show_tool_result(event)
                elif event.type == StreamEventType.ERROR:
                    print(f"\nError: {event.error_msg}")
                elif event.type == StreamEventType.DONE:
                    steps = event.steps

            elapsed = time.time() - t0
            print(f"\nDone — {steps} steps, {elapsed:.1f}s\n")
            session.memory.close()
        except Exception as e:
            print(f"\nError: {e}\n")

    @staticmethod
    def _show_thinking(content: str):
        for line in content.strip().split("\n"):
            print(f"  \x1b[2m{line}\x1b[0m", flush=True)

    @staticmethod
    def _show_tool_start(event):
        name = event.tool_name
        if event.arguments:
            args_str = ", ".join(
                f"{k}={_truncate(repr(v), 60)}"
                for k, v in event.arguments.items()
            )
            print(f"\n  … {name}({args_str})", flush=True)
        else:
            print(f"\n  … {name}", flush=True)

    @staticmethod
    def _show_tool_result(event):
        mark = "✓" if event.ok else "✗"
        if event.content:
            summary = event.content.replace("\n", " ")[:120]
            print(f"  [{mark}] → {summary}", flush=True)
        else:
            print(f"  [{mark}]", flush=True)

    def _handle_slash(self, cmd: str):
        parts = cmd.split()
        op = parts[0].lower()
        if op in ("/exit", "/quit"):
            self._running = False
        elif op == "/help":
            print()
            print("Commands:")
            print("  /help     Show this help")
            print("  /tools    List available tools")
            print("  /exit     Exit REPL")
            print()
        elif op == "/tools":
            try:
                session = create_session(task="")
                for t in session.tools.list_all():
                    caps = ", ".join(c.name for c in t.capabilities)
                    print(f"  {t.name} — {caps}")
                session.memory.close()
            except Exception as e:
                print(f"  Error: {e}")
        else:
            print(f"Unknown command: {op}")


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 3] + "..."
