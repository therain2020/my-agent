"""Minimal CLI entry point — no argparse, no subcommands.

Usage:
    therain2020 <task>
    echo <task> | therain2020

References: browser-harness run.py (130 lines).
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
        print("  echo <task> | therain2020")
        return

    if not args and sys.stdin.isatty():
        print("Usage: therain2020 <task>")
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
