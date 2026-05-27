"""CLI: run command — execute tasks in TODO mode."""

import asyncio

import click

from agent.cli.providers import get_provider
from agent.core import Agent


@click.command()
@click.argument("task")
@click.option("--provider", "-p", default="", help="Provider name (uses first if not specified)")
def run(task: str, provider: str) -> None:
    """Execute a task in TODO mode.

    Examples:
      therain2020-agent run "read README.md and summarize it"
      therain2020-agent run "use the git tool to commit changes with a Chinese message"
    """
    prov = get_provider(provider)
    if prov is None:
        click.echo(
            "No LLM provider configured.\n"
            "Run: therain2020-agent provider add <name> --adapter <anthropic|openai|deepseek|custom> "
            "--api-key-env <ENV_VAR> --model <model>",
            err=True,
        )
        return

    agent = Agent()
    agent.setup()
    agent.set_provider(prov, None)

    click.echo(f"Running: {task}")
    click.echo(f"Tools available: {len(agent.registry.list_all())}")
    click.echo()

    try:
        result = asyncio.run(agent.run(task))
    except KeyboardInterrupt:
        click.echo("\nInterrupted.")
        agent.teardown()
        return
    except Exception as e:
        click.echo(f"\nError: {e}", err=True)
        agent.teardown()
        return

    agent.teardown()

    click.echo()
    if result["success"]:
        click.echo(f"[OK] Complete - {result['steps']} steps, {result['duration_seconds']}s")
    else:
        click.echo(f"[FAILED] {result['error']}")
    if result["tools_used"]:
        click.echo(f"Tools: {', '.join(result['tools_used'])}")
