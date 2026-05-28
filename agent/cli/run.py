"""CLI: run command — execute tasks in TODO mode."""

import asyncio

import click

from agent.cli.autodetect import detect_from_env
from agent.cli.providers import get_provider
from agent.core import Agent


@click.command()
@click.argument("task")
@click.option("--mode", "-m", type=click.Choice(["auto", "todo", "goal"]), default="auto",
              help="Execution mode (auto-detects by default)")
@click.option("--provider", "-p", default="", help="Provider name (auto-detects from env if not specified)")
def run(task: str, mode: str, provider: str) -> None:
    """Execute a task.

    Auto-detects mode: numbered steps → TODO, otherwise → Goal.
    Auto-detects provider from environment variables (DEEPSEEK_API_KEY, etc.)

    Examples:
      therain2020-agent run "read README.md and summarize it"
      therain2020-agent run "fix the login bug" --mode goal
    """
    # Try named provider first, then auto-detect from env
    prov = get_provider(provider) if provider else None
    prov_config = None
    if prov is None:
        prov, prov_config, _ = detect_from_env()

    if prov is None:
        click.echo(
            "No LLM provider found.\n"
            "Set an API key: $env:DEEPSEEK_API_KEY = \"sk-...\"\n"
            "Or: therain2020-agent provider add <name> --api-key-env <VAR> --model <model>",
            err=True,
        )
        return

    agent = Agent()
    agent.setup()
    agent.set_provider(prov, prov_config)

    # Auto-detect mode
    if mode == "auto":
        # Goal-like: long descriptive text without numbered steps
        mode = "goal" if len(task) > 30 and not any(
            task.strip().startswith(str(i)) for i in range(1, 10)
        ) else "todo"

    click.echo(f"Running [{mode}]: {task}")
    click.echo(f"Tools available: {len(agent.registry.list_all())}")
    click.echo()

    try:
        if mode == "goal":
            result = asyncio.run(agent.goal_run(task))
        else:
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
