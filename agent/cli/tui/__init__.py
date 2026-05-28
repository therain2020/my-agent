"""Textual TUI for therain2020-agent — Claude Code-style terminal interface."""

from agent.cli.tui.app import AgentTui


def run_tui(provider=None):
    """Launch the Textual TUI."""
    app = AgentTui(provider=provider)
    app.run()
