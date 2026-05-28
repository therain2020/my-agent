"""Minimal CLI entry point — no argparse, no subcommands.

Usage:
    therain2020 <task>
    therain2020 --tui
    therain2020 --repl
    echo <task> | therain2020
"""

from __future__ import annotations

import asyncio
import sys

from .agent import run
from .session import create_session


async def main():
    args = sys.argv[1:]

    if args and args[0] in ("-h", "--help"):
        print("Usage:")
        print("  therain2020 <task>")
        print("  therain2020 --tui")
        print("  therain2020 --repl")
        print("  echo <task> | therain2020")
        return

    if args and args[0] == "--tui":
        from .cli.tui import run_tui
        run_tui()
        return

    if args and args[0] == "--repl":
        from .cli.repl import run_repl
        run_repl()
        return

    if not args and sys.stdin.isatty():
        print("Usage: therain2020 <task>")
        print("       therain2020 --tui     (Textual UI)")
        print("       therain2020 --repl    (terminal REPL)")
        print("       echo <task> | therain2020")
        sys.exit(1)

    task = " ".join(args) if args else sys.stdin.read().strip()
    if not task:
        print("Error: empty task", file=sys.stderr)
        sys.exit(1)

    try:
        session = create_session(task=task)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    result = await run(task, session)
    print(result)


def cli():
    asyncio.run(main())


if __name__ == "__main__":
    cli()
