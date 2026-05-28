"""CLI entry point for therain2020-agent (legacy).

Running `therain2020-agent` without arguments starts the interactive REPL.
For the new thin harness, use `therain2020` instead.
"""

import sys

import click


@click.group(invoke_without_command=True)
@click.version_option(version="0.8.0", prog_name="therain2020-agent")
@click.pass_context
def main(ctx):
    """therain2020-agent — AI agent.

    Run without arguments to start the interactive REPL.
    For the new thin harness, use `therain2020` command.
    """
    if ctx.invoked_subcommand is None:
        provider = None
        args = sys.argv[1:]
        for i, arg in enumerate(args):
            if arg in ("--provider", "-p") and i + 1 < len(args):
                provider = args[i + 1]
                break
            if arg in ("--repl", "--no-tui"):
                from .repl import run_repl
                run_repl(provider=provider)
                ctx.exit()

        try:
            from .tui import run_tui
            run_tui(provider=provider)
        except ImportError:
            from .repl import run_repl
            run_repl(provider=provider)
        ctx.exit()


if __name__ == "__main__":
    main()
