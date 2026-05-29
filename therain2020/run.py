"""Minimal CLI — Claude Code style.

Usage:
    therain2020 --setup       (one-time provider config)
    therain2020 <task>
    therain2020 --repl
    echo <task> | therain2020
"""

from __future__ import annotations

import asyncio
import sys

from .agent import run
from .session import create_session


async def _run_task(task: str):
    try:
        session = create_session(task=task)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    result = await run(task, session)
    print(result)


async def _run_repl():
    from .cli.repl import AgentRepl

    repl = AgentRepl()
    await repl.start()


def cli():
    args = sys.argv[1:]

    if args and args[0] in ("-h", "--help"):
        print("Usage:")
        print("  therain2020 --setup    (one-time config)")
        print("  therain2020 --repl     (interactive)")
        print("  therain2020 <task>")
        print("  echo <task> | therain2020")
        return

    if args and args[0] == "--setup":
        from .setup_wizard import run_setup
        run_setup()
        return

    if args and args[0] == "--repl":
        asyncio.run(_run_repl())
        return

    if not args and sys.stdin.isatty():
        print("Usage: therain2020 --setup")
        print("       therain2020 --repl")
        print("       therain2020 <task>")
        print("       echo <task> | therain2020")
        sys.exit(1)

    task = " ".join(args) if args else sys.stdin.read().strip()
    if not task:
        print("Error: empty task", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_run_task(task))


if __name__ == "__main__":
    cli()
