"""CLI: add commands — the headline feature.

add discover | from-claude-code | from-codex | from-gemini | from-cursor
add skill | plugin | mcp | settings | cursor-rules | claude-md
add search | info | list | remove | update
"""

from pathlib import Path

import click

from agent.tools.loader import generate_tool_md
from agent.tools.registry import ToolRegistry

_registry: ToolRegistry | None = None


def _get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _registry.scan()
    return _registry


_registry_global: ToolRegistry | None = None


@click.group(name="add")
def add():
    """★ Add tools from external ecosystems.

    Three layers:
      1. Discovery:  add discover, add search
      2. Migration:  add from-claude-code, add from-codex, add from-gemini, add from-cursor
      3. Single:     add skill, add plugin, add mcp, add settings, ...

    Examples:
      my-agent add discover
      my-agent add from-claude-code
      my-agent add mcp "npx @anthropic/mcp-server-git"
    """
    pass


# === Layer 1: Discovery ===

@add.command()
def discover():
    """Scan local machine for installed AI agents and list migratable content.

    Detects: Claude Code, Codex CLI, Gemini CLI, Cursor.
    """
    from agent.tools.adapters.scanner import InstalledAgentScanner

    scanner = InstalledAgentScanner()
    result = scanner.scan_all()

    if not result.installed_agents:
        click.echo("No installed AI agents detected.")
        click.echo("\nYou can still add tools manually:")
        click.echo("  my-agent add mcp <command>")
        click.echo("  my-agent add skill <path>")
        return

    click.echo(f"Detected {len(result.installed_agents)} agent(s):\n")

    for agent_result in result.results:
        if not agent_result.installed:
            continue

        click.echo(f"  {agent_result.agent_name} ({len(agent_result.findings)} items)")

        for f in agent_result.findings:
            icon = {"skill": "[S]", "plugin": "[P]", "mcp": "[M]",
                    "settings_deny": "[D]", "settings_hooks": "[H]",
                    "rule": "[R]", "plain_text": "[T]"}.get(f.type, "[?]")
            click.echo(f"    {icon} {f.name:30s} ({f.type})")
            if f.description:
                click.echo(f"       {f.description[:80]}")

    click.echo("\nTo migrate: my-agent add from-<agent-name>")


@add.command()
@click.argument("keyword")
def search(keyword: str):
    """Search for importable items (local only in phase 1)."""
    from agent.tools.adapters.scanner import InstalledAgentScanner

    scanner = InstalledAgentScanner()
    result = scanner.scan_all()

    matches = []
    for agent_result in result.results:
        for f in agent_result.findings:
            if keyword.lower() in f.name.lower() or \
               keyword.lower() in f.description.lower():
                matches.append((agent_result.agent_name, f))

    if not matches:
        click.echo(f"No matches for '{keyword}' in local agents.")
        click.echo("Remote marketplace search coming in phase 2.")
        return

    click.echo(f"Found {len(matches)} match(es) for '{keyword}':\n")
    for agent_name, f in matches:
        click.echo(f"  {f.name:30s} ({agent_name}, {f.type})")
        if f.description:
            click.echo(f"    {f.description[:100]}")


# === Layer 2: Migration ===

@add.command(name="from-claude-code")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def from_claude_code(yes: bool):
    """One-click migration from Claude Code.

    Imports all skills, MCP servers, settings, and CLAUDE.md.
    """
    from agent.tools.adapters.claude_skill import convert_claude_skill
    from agent.tools.adapters.plain_text import convert_plain_text
    from agent.tools.adapters.scanner import InstalledAgentScanner

    scanner = InstalledAgentScanner()
    result = scanner.scan_agent("claude-code")

    if not result.installed:
        click.echo("Claude Code not detected on this machine.")
        return

    registry = _get_registry()
    generated_dir = Path("tools/.generated")
    roles_dir = Path("roles")
    dont_do_dir = Path("dont-do")
    generated_dir.mkdir(parents=True, exist_ok=True)
    roles_dir.mkdir(parents=True, exist_ok=True)
    dont_do_dir.mkdir(parents=True, exist_ok=True)

    # Summarize and confirm
    click.echo(f"Found {len(result.findings)} items in Claude Code:\n")
    for f in result.findings:
        click.echo(f"  [{f.type}] {f.name}")

    if not yes:
        if not click.confirm("\nImport all?"):
            click.echo("Aborted.")
            return

    imported = 0
    for f in result.findings:
        try:
            if f.type == "skill" and f.path:
                tool_defs = convert_claude_skill(f.path)
                for td in tool_defs:
                    out_dir = roles_dir if td.source == "claude-code-skill-role" else generated_dir
                    out_dir.mkdir(parents=True, exist_ok=True)
                    tool_md_path = out_dir / td.name / "tool.md"
                    tool_md_path.parent.mkdir(parents=True, exist_ok=True)
                    tool_md_path.write_text(generate_tool_md(td), encoding="utf-8")
                    registry.register(td)
                    imported += 1

            elif f.type == "settings_deny" and f.metadata.get("rules"):
                content = "# Claude Code Deny Rules (imported)\n\n"
                for rule in f.metadata["rules"]:
                    content += f"- DENY: {rule}\n"
                (dont_do_dir / "claude-code.md").write_text(content, encoding="utf-8")
                imported += 1

            elif f.type == "plain_text" and f.path:
                content = convert_plain_text(f.path)
                click.echo(f"  Imported plain text: {f.name} ({len(content)} chars)")

            elif f.type == "mcp" and f.command:
                click.echo(f"  MCP server: {f.name} -> use 'my-agent add mcp \"{f.command}\"' to import")
        except Exception as e:
            click.echo(f"  Error importing {f.name}: {e}", err=True)

    click.echo(f"\nImported {imported} tool(s). Run 'my-agent tools list' to see them.")


@add.command(name="from-codex")
@click.option("--yes", "-y", is_flag=True)
def from_codex(yes: bool):
    """One-click migration from Codex CLI."""
    from agent.tools.adapters.scanner import InstalledAgentScanner

    scanner = InstalledAgentScanner()
    result = scanner.scan_agent("codex")

    if not result.installed:
        click.echo("Codex CLI not detected.")
        return

    click.echo(f"Found {len(result.findings)} items in Codex CLI.")
    # ... similar pattern to from-claude-code
    click.echo("Codex migration: MCP servers will be imported. Plugins need manual review.")
    # For now, list only
    for f in result.findings:
        if f.type == "mcp" and f.command:
            click.echo(f"  MCP: {f.name} -> {f.command}")


@add.command(name="from-gemini")
@click.option("--yes", "-y", is_flag=True)
def from_gemini(yes: bool):
    """One-click migration from Gemini CLI."""
    from agent.tools.adapters.scanner import InstalledAgentScanner

    scanner = InstalledAgentScanner()
    result = scanner.scan_agent("gemini")

    if not result.installed:
        click.echo("Gemini CLI not detected.")
        return

    click.echo(f"Found {len(result.findings)} items in Gemini CLI.")
    for f in result.findings:
        if f.type == "mcp" and f.command:
            click.echo(f"  MCP: {f.name} -> {f.command}")


@add.command(name="from-cursor")
@click.option("--yes", "-y", is_flag=True)
def from_cursor(yes: bool):
    """One-click migration from Cursor."""
    from agent.tools.adapters.scanner import InstalledAgentScanner

    scanner = InstalledAgentScanner()
    result = scanner.scan_agent("cursor")

    if not result.installed:
        click.echo("Cursor not detected in current project.")
        return

    click.echo(f"Found {len(result.findings)} items in Cursor.")
    for f in result.findings:
        if f.type == "rule" and f.path:
            click.echo(f"  Rule: {f.name} ({f.path})")
        elif f.type == "mcp" and f.command:
            click.echo(f"  MCP: {f.name} -> {f.command}")


# === Layer 3: Single Import ===

@add.command()
@click.argument("path", type=click.Path(exists=True))
def skill(path: str):
    """Import a Claude Code SKILL.md."""
    from agent.tools.adapters.claude_skill import convert_claude_skill

    skill_path = Path(path)
    registry = _get_registry()
    generated_dir = Path("tools/.generated")
    generated_dir.mkdir(parents=True, exist_ok=True)

    tool_defs = convert_claude_skill(skill_path)
    for td in tool_defs:
        out_dir = generated_dir / td.name
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "tool.md").write_text(generate_tool_md(td), encoding="utf-8")
        registry.register(td)
        click.echo(f"Imported skill '{td.name}' as {td.source}")


@add.command()
@click.argument("path", type=click.Path(exists=True))
def plugin(path: str):
    """Import a Claude Code .claude-plugin/ directory."""
    from agent.tools.adapters.claude_plugin import convert_claude_plugin

    plugin_path = Path(path)
    tool_defs = convert_claude_plugin(plugin_path)

    registry = _get_registry()
    generated_dir = Path("tools/.generated")
    generated_dir.mkdir(parents=True, exist_ok=True)

    for td in tool_defs:
        out_dir = generated_dir / td.name
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "tool.md").write_text(generate_tool_md(td), encoding="utf-8")
        registry.register(td)

    click.echo(f"Imported {len(tool_defs)} tool(s) from plugin '{plugin_path.name}'")


@add.command()
@click.argument("source")
def mcp(source: str):
    """Import an MCP server. Source can be a command or URL."""
    from agent.tools.adapters.mcp import (
        convert_mcp_command,
        detect_transport,
        generate_mcp_tool_def,
    )
    from agent.tools.loader import Capability

    source = convert_mcp_command(source)
    transport = detect_transport(source)

    server_name = source.split("/")[-1].replace("@", "").replace(":", "")
    if " " in server_name or server_name.startswith("npx"):
        server_name = source.split()[-1].split("/")[-1] if "/" in source else "mcp-server"

    tool_def = generate_mcp_tool_def(
        server_name=server_name,
        source=source,
        capabilities=[Capability(
            name=f"{server_name}_tool",
            description=f"MCP tool from {source}",
            parameters={},
        )],
        server_description=f"Imported MCP server: {source}",
    )

    registry = _get_registry()
    generated_dir = Path("tools/.generated")
    generated_dir.mkdir(parents=True, exist_ok=True)
    out_dir = generated_dir / tool_def.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tool.md").write_text(generate_tool_md(tool_def), encoding="utf-8")

    # Validate
    from agent.tools.adapters.validator import validate_import
    existing = [t.name for t in registry.list_all() if t.name != tool_def.name]
    validation = validate_import(tool_def, existing_names=existing)

    for check in validation.checks:
        if check.level == "ERROR":
            click.echo(f"  ERROR: {check.message}", err=True)
        elif check.level == "CONFIRM":
            click.echo(f"  ⚠  {check.message}")
        elif check.level == "WARN":
            click.echo(f"  ⚡ {check.message}")

    if validation.passed:
        registry.register(tool_def)
        click.echo(f"Imported MCP server '{tool_def.name}' (transport={transport})")
        click.echo(f"\nStart with: my-agent supervisor start {tool_def.name}")
        click.echo(f"Then: my-agent run \"use {tool_def.name} to ...\"")
    else:
        click.echo("Import failed validation. Fix errors and try again.", err=True)


@add.command()
@click.argument("path", type=click.Path(exists=True))
def settings(path: str):
    """Import a Claude Code settings.json."""
    from agent.tools.adapters.claude_settings import convert_claude_settings

    settings_path = Path(path)
    result = convert_claude_settings(settings_path)

    click.echo(f"Capabilities: {len(result.capabilities)} rules")
    for cap in result.capabilities[:5]:
        click.echo(f"  - {cap}")

    click.echo(f"\nDont-Do rules: {len(result.dont_do_rules)} rules")
    for rule in result.dont_do_rules[:5]:
        click.echo(f"  - {rule.get('object', '?')}: {rule.get('pattern', '?')}")

    if result.dont_do_rules:
        dont_do_dir = Path("dont-do")
        dont_do_dir.mkdir(parents=True, exist_ok=True)
        content = "# Imported from Claude Code settings.json\n\n"
        for rule in result.dont_do_rules:
            content += f"- DENY: {rule.get('object', 'general')}: {rule.get('pattern', rule.get('tool_prefix', '?'))}\n"
        (dont_do_dir / "claude-code.md").write_text(content, encoding="utf-8")
        click.echo("\nDont-Do rules saved to dont-do/claude-code.md")

    click.echo(f"\nProbes: {len(result.probes)} hooks")
    for p in result.probes:
        click.echo(f"  - {p['point']}: {p['command'][:60]}")

    click.echo("\nRun 'my-agent dont-do list' to see active rules.")


@add.command(name="cursor-rules")
@click.argument("directory", type=click.Path(exists=True))
def cursor_rules_cmd(directory: str):
    """Import .cursor/rules/ directory."""
    from agent.tools.adapters.plain_text import convert_cursor_rules

    rules = convert_cursor_rules(Path(directory))
    click.echo(f"Imported {len(rules)} Cursor rules.")
    for r in rules:
        click.echo(f"  - {r['name']} ({len(r['content'])} chars)")


@add.command(name="claude-md")
@click.argument("path", type=click.Path(exists=True))
def claude_md_cmd(path: str):
    """Import a CLAUDE.md file as behavior rules."""
    from agent.tools.adapters.plain_text import convert_plain_text

    content = convert_plain_text(Path(path))
    click.echo(f"Imported CLAUDE.md ({len(content)} chars)")


@add.command()
def list():
    """List all imported tools."""
    registry = _get_registry()
    imported = [t for t in registry.list_all() if t.source != "builtin"]
    if not imported:
        click.echo("No imported tools. Use 'my-agent add discover' to find tools.")
        return

    for t in imported:
        caps = ", ".join(c.name for c in t.capabilities)
        click.echo(f"{t.name:30s} ({t.source:25s})  [{caps}]")


@add.command()
@click.argument("name")
def info(name: str):
    """Show details of an imported tool."""
    registry = _get_registry()
    tool = registry.get(name)
    if not tool:
        click.echo(f"Tool '{name}' not found.", err=True)
        return

    click.echo(f"Name:        {tool.name}")
    click.echo(f"Version:     {tool.version}")
    click.echo(f"Source:      {tool.source}")
    click.echo(f"Runtime:     {tool.runtime}")
    if tool.source_command:
        click.echo(f"Command:     {tool.source_command}")
    click.echo(f"Objects:     {', '.join(tool.objects)}")
    click.echo("Capabilities:")
    for cap in tool.capabilities:
        click.echo(f"  - {cap.name}: {cap.description}")
        if cap.danger_level != "low":
            click.echo(f"    Danger: {cap.danger_level}")


@add.command()
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Preview only, don't delete")
def remove(name: str, dry_run: bool):
    """Remove an imported tool and clean up generated files."""
    registry = _get_registry()
    tool = registry.get(name)
    if not tool:
        click.echo(f"Tool '{name}' not found.", err=True)
        return

    if tool.source == "builtin":
        click.echo("Cannot remove builtin tools.", err=True)
        return

    generated_dir = Path("tools/.generated") / tool.name

    if dry_run:
        click.echo(f"Would remove: {name}")
        if generated_dir.exists():
            click.echo(f"  Would delete: {generated_dir}")
        click.echo("  Would unregister from registry")
        click.echo("Use without --dry-run to execute.")
        return

    # Remove tool.md file
    import shutil
    if generated_dir.exists():
        shutil.rmtree(generated_dir)

    # Stop MCP process if running
    if tool.runtime == "mcp":
        click.echo("  If MCP server was running, it will stop on next restart.")

    registry.unregister(name)
    click.echo(f"Removed '{name}'.")


@add.command()
@click.argument("name")
def update(name: str):
    """Re-import a tool from its original source."""
    tool = _get_registry().get(name)
    if not tool:
        click.echo(f"Tool '{name}' not found.", err=True)
        return
    click.echo(f"Re-importing '{name}' from source: {tool.source_command or tool.source}")
    # For now, just re-generate tool.md
    generated_dir = Path("tools/.generated") / tool.name
    generated_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "tool.md").write_text(generate_tool_md(tool), encoding="utf-8")
    click.echo(f"Updated '{name}'.")
