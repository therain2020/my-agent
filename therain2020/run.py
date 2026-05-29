"""therain2020 — Claude Code-style agent CLI.

Usage:
    therain2020 <task>
    therain2020 --repl
    echo <task> | therain2020
"""

from __future__ import annotations

import asyncio
import sys


async def _run_task(task: str):
    import time

    from .agent import run_stream
    from .cli.app import EventType, _status_bar
    from .session import create_session
    t0 = time.time()
    steps = 0
    tokens = 0
    model = ""
    try:
        session = create_session(task=task)
        model = session.provider.model
        print()
        async for event in run_stream(task, session):
            if event.type == EventType.TEXT:
                for line in event.content.strip().split("\n"):
                    print(f"  \x1b[90m⎿\x1b[0m  {line}", flush=True)
            elif event.type == EventType.DONE:
                steps = event.steps
                tokens = event.tokens
        elapsed = time.time() - t0
        _status_bar(model, steps, tokens, elapsed)
        session.memory.close()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def _run_repl():
    from .cli.app import Repl
    repl = Repl()
    await repl.start()


def cli():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print("Usage: therain2020 <task>")
        print("       therain2020 --repl")
        print("       echo <task> | therain2020")
        return
    if args and args[0] == "--repl":
        asyncio.run(_run_repl())
        return
    if not args and sys.stdin.isatty():
        print("Usage: therain2020 --repl")
        sys.exit(1)
    task = " ".join(args) if args else sys.stdin.read().strip()
    if not task:
        sys.exit(1)
    asyncio.run(_run_task(task))


if __name__ == "__main__":
    cli()
