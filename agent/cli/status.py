"""CLI: status, pause, resume commands."""

import click


@click.group(name="status")
def status():
    """Session management."""
    pass


@status.command()
def show():
    """Show current session status."""
    click.echo("Session status: not yet implemented (phase 2)")


@status.command()
def pause():
    """Pause current session."""
    click.echo("Session paused (not yet implemented)")


@status.command()
def resume():
    """Resume paused session."""
    click.echo("Session resumed (not yet implemented)")
