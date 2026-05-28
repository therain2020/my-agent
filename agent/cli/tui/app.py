"""Textual TUI app — Claude Code-style terminal interface.

Layout:
  ┌─ Header ──────────────────────────────┐
  │  therain2020-agent v0.7.0  session:abc │
  ├─ Transcript ──────────────────────────┤
  │  > user message                        │
  │  ┌ Thinking ──────────────────────┐    │
  │  │ model reasoning...             │    │
  │  └────────────────────────────────┘    │
  │  → tool.cap ✓                         │
  │  ## Response markdown                  │
  │  [OK] 3 steps in 8.2s                 │
  ├─ Input ───────────────────────────────┤
  │  > _                                   │
  ├─ Footer ──────────────────────────────┤
  │  deepseek-chat | /help | Ctrl+C exit  │
  └────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Header, Input, Markdown, Static

from agent.core import Agent
from agent.streaming import StreamEventType
from agent.tools.adapters.browser_harness import BrowserHarnessAdapter


class ThinkingBlock(Static):
    """A collapsible thinking/reasoning block."""

    expanded = reactive(True)

    def __init__(self):
        super().__init__("", classes="thinking-block")
        self._content = ""

    def append(self, text: str) -> None:
        self._content += text
        self._refresh()

    def toggle(self) -> None:
        self.expanded = not self.expanded
        self._refresh()

    def _refresh(self) -> None:
        if self.expanded:
            lines = ["┌─ Thinking ─".ljust(50, "─") + "┐"]
            for line in self._content.split("\n")[-20:]:
                lines.append(f"│ {line[:94]}".ljust(99) + "│")
            lines.append("└".ljust(50, "─") + "┘")
            self.update("\n".join(lines))
        else:
            n = len(self._content)
            self.update(f"· Thinking... ({n} chars)  [dim]Ctrl+T to expand[/]")


class ToolLine(Static):
    """A single tool call line with status."""

    def __init__(self, name: str, cap: str):
        self.tool_name = name
        self.tool_cap = cap
        super().__init__(f"  → [cyan]{name}[/].[bold]{cap}[/]  ", classes="tool-line")

    def done(self, ok: bool = True) -> None:
        mark = "[green]✓[/]" if ok else "[yellow]⚠[/]"
        self.update(f"  → [cyan]{self.tool_name}[/].[bold]{self.tool_cap}[/]  {mark}")


class AgentTui(App):
    """Textual TUI for therain2020-agent."""

    CSS = """
    #transcript {
        overflow-y: auto;
        padding: 1 2;
        scrollbar-size: 1 0;
    }

    .thinking-block {
        color: grey;
        margin: 1 2;
        height: auto;
        min-height: 3;
    }

    .tool-line {
        color: grey;
        padding: 0 2;
        height: 1;
    }

    .response {
        margin-top: 1;
        padding: 0 2;
    }

    #input-area {
        dock: bottom;
        height: 3;
        padding: 0 1;
        border-top: solid grey;
    }

    #prompt-input {
        width: 100%;
    }

    #footer-bar {
        dock: bottom;
        height: 1;
        color: grey;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+t", "toggle_thinking", "Toggle thinking"),
        Binding("ctrl+c", "quit", "Exit"),
        Binding("escape", "clear_input", "Clear"),
        Binding("up", "history_up", "History ↑", show=False),
        Binding("down", "history_down", "History ↓", show=False),
    ]

    def __init__(self, provider=None):
        super().__init__()
        self._provider_arg = provider
        self._agent: Agent | None = None
        self._history: list[str] = []
        self._history_idx: int = -1
        self._thinking_block: ThinkingBlock | None = None
        self._tool_lines: list[ToolLine] = []
        self._running = False

    def compose(self) -> ComposeResult:
        """Build the layout."""
        yield Header(show_clock=False)
        yield VerticalScroll(id="transcript")
        with Container(id="input-area"):
            yield Input(placeholder="Type a task or /help for commands...", id="prompt-input")
        yield Static(id="footer-bar")

    def on_mount(self) -> None:
        """Initialize agent and show welcome."""
        self.query_one(Header).tall = False

        # Setup agent
        data_dir = Path.home() / ".therain2020-agent"
        for sub in ["memory", "tools", "tools/.generated", "dont-do"]:
            (data_dir / sub).mkdir(parents=True, exist_ok=True)

        self._agent = Agent()
        self._agent.setup()

        # Auto-detect provider
        from agent.cli.autodetect import detect_from_env
        detected, config, source = detect_from_env()
        if detected:
            self._agent.set_provider(detected, config)
            model = config.model if config else "unknown"
        else:
            model = "none"

        # Register browser tools
        try:
            BrowserHarnessAdapter(self._agent.registry).register()
        except Exception:
            pass

        # Header
        self.title = "therain2020-agent"
        self.sub_title = f"v0.7.0  model:[cyan]{model}[/]  session:{self._agent.session_id}"

        # Footer
        self.query_one("#footer-bar", Static).update(
            " [dim]Ctrl+T:thinking[/] | [dim]↑↓:history[/] | "
            "[dim]/help[/] | [dim]Ctrl+C:exit[/]"
        )

        # Welcome
        self._add_to_transcript(
            "[bold]therain2020-agent[/] [dim]v0.7.0[/]\n"
            f"Model: [cyan]{model}[/] [dim]({source})[/]\n"
            "Type a task or [dim]/help[/] for commands.\n"
        )

        # Focus input
        self.query_one("#prompt-input", Input).focus()

    # ── Input handling ──

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        text = event.value.strip()
        if not text:
            return

        # Save to history
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history_idx = len(self._history)

        # Slash commands
        if text.startswith("/"):
            self._handle_slash(text)
            event.input.clear()
            return

        # Prevent double-submit
        if self._running:
            return

        # Show user message and execute
        self._add_to_transcript(f"\n[bold]> {text}[/]")
        self._run_task(text)
        event.input.clear()

    def action_clear_input(self) -> None:
        self.query_one("#prompt-input", Input).clear()

    def action_history_up(self) -> None:
        if not self._history:
            return
        inp = self.query_one("#prompt-input", Input)
        if self._history_idx == len(self._history):
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        inp.value = self._history[self._history_idx]
        inp.action_end()

    def action_history_down(self) -> None:
        inp = self.query_one("#prompt-input", Input)
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            inp.value = self._history[self._history_idx]
        else:
            self._history_idx = len(self._history)
            inp.value = ""
        inp.action_end()

    # ── Slash commands ──

    def _handle_slash(self, text: str) -> None:
        cmd = text.strip().lower()
        parts = cmd.split()

        if parts[0] == "/help":
            self._add_to_transcript(
                "[dim]── Commands ──[/]\n"
                "[/help clear tools mode history skills think exit]\n"
                "[dim]── Keys ──[/]\n"
                "[dim]Ctrl+T toggle thinking | ↑↓ history | Ctrl+C exit[/]"
            )
        elif parts[0] == "/clear":
            self.query_one("#transcript", VerticalScroll).remove_children()
        elif parts[0] == "/tools":
            tools = self._agent.registry.list_all()
            lines = ["[dim]── Tools ──[/]"]
            for t in sorted(tools, key=lambda x: x.name):
                caps = ", ".join(c.name for c in t.capabilities)
                lines.append(f"  [cyan]{t.name}[/] [dim]{caps}[/]")
            self._add_to_transcript("\n".join(lines))
        elif parts[0] == "/skills":
            try:
                skills = self._agent.skill_repo.get_active(limit=20)
                if not skills:
                    self._add_to_transcript("[dim]No skills yet.[/]")
                else:
                    lines = ["[dim]── Skills ──[/]"]
                    for s in skills:
                        lines.append(f"  [cyan]{s.name}[/] [dim]uses={s.uses} score={s.score}[/]")
                    self._add_to_transcript("\n".join(lines))
            except Exception:
                self._add_to_transcript("[dim]Skills not available.[/]")
        elif parts[0] == "/exit":
            self.exit()
        else:
            self._add_to_transcript(f"[dim]Unknown: {cmd}. Type /help.[/]")

    # ── Task execution ──

    @work(thread=False, exclusive=True)
    async def _run_task(self, task: str) -> None:
        """Execute a task as a Textual worker (keeps UI responsive)."""
        self._running = True
        self._thinking_block = None
        self._tool_lines = []
        start = time.time()

        try:
            if self._agent.supports_structured_stream():
                async for event in self._agent.run_stream(task):
                    if event.type == StreamEventType.THINKING:
                        self._on_stream_thinking(event.content)
                    elif event.type == StreamEventType.TEXT:
                        self._on_stream_text(event.content)
                    elif event.type == StreamEventType.TOOL_START:
                        self._on_stream_tool_start(event.tool_name, event.capability)
                    elif event.type == StreamEventType.TOOL_RESULT:
                        self._on_stream_tool_result(event.tool_name, event.capability, event.ok)
                    elif event.type == StreamEventType.ERROR:
                        self._add_to_transcript(f"[red]Error: {event.content}[/]")
                    elif event.type == StreamEventType.DONE:
                        duration = round(time.time() - start, 1)
                        if event.success:
                            self._add_to_transcript(
                                f"\n[green][OK][/] {event.steps} steps in {duration}s"
                            )
                        else:
                            self._add_to_transcript(
                                f"\n[red][FAILED][/] {event.error_msg}"
                            )
            else:
                # Fallback: legacy execution
                self._add_to_transcript("[dim]  Thinking...[/]")
                result = await self._agent.run(task)
                duration = round(time.time() - start, 1)
                if result["success"]:
                    self._add_to_transcript(
                        f"[green][OK][/] {result['steps']} steps in {duration}s"
                    )
                else:
                    self._add_to_transcript(f"[red][FAILED][/] {result.get('error', '')}")
        except Exception as e:
            self._add_to_transcript(f"[red]Error: {e}[/]")
        finally:
            self._running = False
            self._add_to_transcript("")  # spacer
            self.query_one("#prompt-input", Input).focus()

    def _on_stream_thinking(self, content: str) -> None:
        if self._thinking_block is None:
            self._thinking_block = ThinkingBlock()
            self.query_one("#transcript", VerticalScroll).mount(self._thinking_block)
            self._thinking_block.scroll_visible()
        self._thinking_block.append(content)

    def _on_stream_text(self, content: str) -> None:
        self._add_to_transcript(content, cls="response")

    def _on_stream_tool_start(self, name: str, cap: str) -> None:
        line = ToolLine(name, cap)
        self.query_one("#transcript", VerticalScroll).mount(line)
        self._tool_lines.append(line)
        line.scroll_visible()

    def _on_stream_tool_result(self, name: str, cap: str, ok: bool) -> None:
        # Mark the matching tool line as done
        for line in reversed(self._tool_lines):
            if line.tool_name == name and line.tool_cap == cap:
                line.done(ok)
                break

    def action_toggle_thinking(self) -> None:
        if self._thinking_block:
            self._thinking_block.toggle()

    # ── helpers ──

    def _add_to_transcript(self, text: str, cls: str = "") -> None:
        """Append a message to the transcript area."""
        w: Static | Markdown
        if cls == "response" and len(text) > 100:
            w = Markdown(text)
        else:
            w = Static(text)
        if cls:
            w.add_class(cls)
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.mount(w)
        w.scroll_visible()
