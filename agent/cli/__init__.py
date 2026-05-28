"""CLI entry point and subcommand groups.

Running `therain2020-agent` without arguments starts the interactive REPL.
Use subcommands for one-shot operations: provider, add, publish, run, info, status.
"""

import sys

import click

from agent.cli import add, info, providers, publish, run, status


@click.group(invoke_without_command=True)
@click.version_option(version="0.7.1", prog_name="therain2020-agent")
@click.pass_context
def main(ctx):
    """therain2020-agent — self-healing AI agent.

    Run without arguments to start the interactive REPL.
    Use subcommands for one-shot operations.

    Quick start:
      therain2020-agent                                  # interactive REPL
      therain2020-agent provider add ...                 # configure LLM
      therain2020-agent add discover                     # find local tools
      therain2020-agent run "fix the login bug"          # one-shot task
    """
    if ctx.invoked_subcommand is None:
        # No subcommand → start Textual TUI (or fallback to REPL)
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

        # Try Textual TUI first
        try:
            from .tui import run_tui
            run_tui(provider=provider)
        except ImportError:
            from .repl import run_repl
            run_repl(provider=provider)
        ctx.exit()


main.add_command(providers.provider)
main.add_command(add.add)
main.add_command(publish.publish)
main.add_command(run.run)
main.add_command(info.info)
main.add_command(status.status)


if __name__ == "__main__":
    main()
