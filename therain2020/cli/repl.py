"""Streaming REPL — simple read-eval-print loop with Rich rendering.

Migrated from agent/cli/repl.py. Adapted to new therain2020 agent API.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from ..agent import run_stream
from ..cli.streaming import StreamEventType
from ..session import create_session


class AgentRepl:
    """Simple REPL for interactive agent use."""

    def __init__(self):
        self.turn: int = 0
        self.conversation: list[dict] = []
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
                if text.startswith("/"):
                    await self._handle_slash(text)
                elif text.strip():
                    await self._execute(text)
            except (EOFError, KeyboardInterrupt):
                break

        print("Bye.")

    async def _prompt(self) -> str | None:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, lambda: input("> "))
        except RuntimeError:
            return await loop.run_in_executor(None, sys.stdin.readline)

    async def _execute(self, task: str):
        self.turn += 1
        t0 = time.time()

        try:
            session = create_session(task=task)
            print()
            async for event in run_stream(task, session):
                if event.type == StreamEventType.THINKING:
                    print(f"  [dim]{event.content[:500]}[/dim]")
                elif event.type == StreamEventType.TEXT:
                    print(event.content, end="", flush=True)
                elif event.type == StreamEventType.TOOL_START:
                    print(f"\n  ... {event.tool_name}.{event.capability}", flush=True)
                elif event.type == StreamEventType.TOOL_RESULT:
                    mark = "ok" if event.ok else "FAIL"
                    print(f"  [{mark}] {event.tool_name}", flush=True)
                elif event.type == StreamEventType.ERROR:
                    print(f"\n[red]Error: {event.error_msg}[/red]")
                elif event.type == StreamEventType.DONE:
                    elapsed = time.time() - t0
                    print(f"\nDone — {event.steps} steps, {elapsed:.1f}s")
            session.memory.close()
        except Exception as e:
            print(f"\n[red]Error: {e}[/red]")

        print()

    async def _handle_slash(self, cmd: str):
        parts = cmd.split()
        op = parts[0].lower()
        if op in ("/exit", "/quit"):
            self._running = False
        elif op == "/help":
            print("Commands: /help /clear /tools /history /exit")
        elif op == "/clear":
            os.system("cls" if sys.platform == "win32" else "clear")
        elif op == "/tools":
            try:
                session = create_session(task="")
                for t in session.tools.list_all():
                    caps = ", ".join(c.name for c in t.capabilities)
                    print(f"  {t.name} — {caps}")
                session.memory.close()
            except Exception as e:
                print(f"  Error: {e}")
        elif op == "/history":
            for i, entry in enumerate(self.conversation[-20:]):
                print(f"  [{i+1}] {entry.get('task', '')[:100]}")
        else:
            print(f"Unknown command: {op}")


def run_repl():
    repl = AgentRepl()
    asyncio.run(repl.start())
