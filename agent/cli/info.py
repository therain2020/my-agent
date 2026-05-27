"""CLI: info commands — tools list, dont-do list, config show."""

import click

from agent.security import SecurityManager
from agent.tools.registry import ToolRegistry


@click.group(name="info")
def info():
    """Query agent state (procfs-style)."""
    pass


@info.command(name="tools")
@click.option("--source", "-s", default="", help="Filter by source")
def tools_list(source: str):
    """List all registered tools."""
    registry = ToolRegistry(["./tools", "./tools/.generated"])
    registry.scan()

    tools = registry.list_all()
    if source:
        tools = [t for t in tools if t.source == source]

    if not tools:
        click.echo("No tools registered.")
        click.echo("\nAdd tools:")
        click.echo("  therain2020-agent add discover")
        click.echo("  therain2020-agent add from-claude-code")
        click.echo("  therain2020-agent add mcp <command>")
        return

    click.echo(f"{'Name':30s} {'Source':25s} {'Runtime':10s} {'Capabilities'}")
    click.echo("-" * 90)
    for t in sorted(tools, key=lambda x: x.name):
        caps = ", ".join(c.name for c in t.capabilities)
        click.echo(f"{t.name:30s} {t.source:25s} {t.runtime:10s} {caps}")

    click.echo(f"\n{len(tools)} tool(s) total")


@info.command(name="dont-do")
def dont_do_list():
    """List all loaded dont-do rules."""
    security = SecurityManager()
    security.load_rules()

    rules = security.list_rules()
    if not rules:
        click.echo("No dont-do rules loaded.")
        click.echo("\nDont-do rules are imported from:")
        click.echo("  therain2020-agent add from-claude-code  (settings.json permissions.deny)")
        click.echo("  therain2020-agent add settings <path>")
        click.echo("  Or write them manually in dont-do/*.md")
        return

    for name, content in rules.items():
        click.echo(f"\n[{name}]")
        click.echo(content[:200])
        if len(content) > 200:
            click.echo("  ...")


@info.command(name="config")
def config_show():
    """Show current configuration."""
    import yaml

    from agent.config import load_config

    config = load_config()
    # Mask API keys in output
    for p in config.get("llm", {}).get("providers", []):
        if p.get("api_key"):
            p["api_key"] = "***"
        if p.get("api_key_env"):
            p["api_key_env"] = f"{p['api_key_env']} (env var)"

    click.echo(yaml.dump(config, allow_unicode=True, default_flow_style=False))
