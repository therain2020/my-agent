"""CLI entry point and subcommand groups."""

import click

from agent.cli import add, info, providers, publish, run, status


@click.group()
@click.version_option(version="0.1.0", prog_name="therain2020-agent")
def main():
    """therain2020-agent: Add-First Agent skeleton.

    Bring your own LLM. Bring your own tools (Claude Code, Codex, Gemini, MCP).

    Quick start:
      therain2020-agent provider add anthropic --api-key-env ANTHROPIC_API_KEY
      therain2020-agent add discover
      therain2020-agent add from-claude-code
      therain2020-agent tools list
      therain2020-agent run "your task"
    """
    pass


main.add_command(providers.provider)
main.add_command(add.add)
main.add_command(publish.publish)
main.add_command(run.run)
main.add_command(info.info)
main.add_command(status.status)


if __name__ == "__main__":
    main()
