"""Rich streaming display for the REPL — thinking blocks, progress, markdown.

Port of Claude Code's Ink-based streaming UX to Python/rich:
- Thinking content: dim panel, toggle expand with Ctrl+T
- Text streaming: live markdown rendering
- Tool calls: progress with ✓/⚠ indicators
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

_console = Console(highlight=False)


def dim(text: str) -> str:
    return f"[dim]{text}[/dim]"


def bold(text: str) -> str:
    return f"[bold]{text}[/bold]"


def green(text: str) -> str:
    return f"[green]{text}[/green]"


def yellow(text: str) -> str:
    return f"[yellow]{text}[/yellow]"


def red(text: str) -> str:
    return f"[red]{text}[/red]"


def cyan(text: str) -> str:
    return f"[cyan]{text}[/cyan]"


class StreamingDisplay:
    """Live-updating terminal display for streaming agent execution.

    Like Claude Code's REPL screen, but using rich.Live instead of Ink.
    """

    def __init__(self):
        self._thinking_parts: list[str] = []
        self._text_parts: list[str] = []
        self._tool_lines: list[str] = []
        self._status_text = ""
        self._show_thinking = True  # Default: show thinking expanded
        self._thinking_toggle_hint = " [dim](Ctrl+T to hide thinking)[/dim]"
        self._live: Live | None = None
        self._start_time = 0.0

    # ── public API ──

    @contextmanager
    def run(self):
        """Context manager that manages the Live display lifecycle."""
        self._start_time = time.time()
        with Live(self._render(), console=_console, refresh_per_second=10,
                  transient=False, vertical_overflow="visible") as live:
            self._live = live
            try:
                yield self
            finally:
                self._live = None

    def on_thinking(self, chunk: str) -> None:
        self._thinking_parts.append(chunk)
        self._refresh()

    def on_text(self, chunk: str) -> None:
        self._text_parts.append(chunk)
        self._refresh()

    def on_tool_start(self, name: str, cap: str) -> None:
        self._tool_lines.append(f"  {dim('→')} {cyan(name)}.{cap}  ")
        self._refresh()

    def on_tool_result(self, name: str, cap: str, ok: bool = True) -> None:
        # Replace the last pending line with result
        mark = green("✓") if ok else yellow("⚠")
        if self._tool_lines:
            self._tool_lines[-1] = (
                f"  {dim('→')} {cyan(name)}.{cap}  {mark}"
            )
        self._refresh()

    def on_error(self, msg: str) -> None:
        self._tool_lines.append(f"  {red('✗')} {msg}")
        self._refresh()

    def on_done(self, success: bool, steps: int, duration: float,
                tools: list[str], error: str = "") -> None:
        self._status_text = ""
        summary = green("[OK]") if success else red("[FAILED]")
        self._tool_lines.append(
            f"\n{summary} {steps} steps in {duration:.1f}s"
        )
        if tools:
            self._tool_lines.append(dim(f"     tools: {', '.join(tools)}"))
        if error:
            self._tool_lines.append(red(f"     {error}"))
        self._refresh()

    def toggle_thinking(self) -> None:
        """Toggle thinking visibility. Bound to Ctrl+T."""
        self._show_thinking = not self._show_thinking
        self._thinking_toggle_hint = (
            " [dim](Ctrl+T to show thinking)[/dim]"
            if not self._show_thinking
            else " [dim](Ctrl+T to hide thinking)[/dim]"
        )
        self._refresh()

    def set_status(self, text: str) -> None:
        self._status_text = text
        self._refresh()

    # ── internal ──

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())

    def _render(self) -> Group:
        elements: list[Any] = []

        # Status spinner line
        if self._status_text:
            spinner = Spinner("dots", text=self._status_text)
            elements.append(spinner)

        # Thinking block
        thinking = "".join(self._thinking_parts)
        if thinking and self._show_thinking:
            panel = Panel(
                Markdown(thinking),
                title="Thinking",
                title_align="left",
                border_style="dim",
                padding=(0, 1),
            )
            elements.append(panel)
            elements.append(Text(self._thinking_toggle_hint))
        elif thinking and not self._show_thinking:
            elements.append(Text(
                f"[dim]· Thinking... ({len(thinking)} chars) [/dim]"
                + self._thinking_toggle_hint
            ))

        # Tool call lines
        if self._tool_lines:
            elements.append(Text("\n".join(self._tool_lines)))

        # Response text (markdown rendered)
        text = "".join(self._text_parts)
        if text:
            if self._thinking_parts:
                elements.append(Text(""))  # spacer
            elements.append(Markdown(self._sanitize_markdown(text)))

        if not elements:
            elements.append(Text(dim("Waiting...")))

        return Group(*elements)

    @staticmethod
    def _sanitize_markdown(text: str) -> str:
        """Basic sanitization to keep markdown rendering safe."""
        # Remove trailing partial code fences that break rendering
        text = re.sub(r'```\s*$', '```\n', text)
        return text
