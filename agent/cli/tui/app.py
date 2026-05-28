"""Textual TUI — Claude Code-style terminal interface.

Layout (CSS grid):
  ┌─ Header ──────────────────────────┐
  │  therain2020-agent  model:xxx      │
  ├─ Transcript (scrollable) ─────────┤
  │  > user message                    │
  │  ┌ Thinking ──────────────────┐    │
  │  │ reasoning...               │    │
  │  └────────────────────────────┘    │
  │  → tool.cap ✓                     │
  │  Response markdown                 │
  ├─ Bottom ──────────────────────────┤
  │  > _                               │  ← TextArea input
  │  model | Ctrl+T:think | /help      │  ← status line
  └────────────────────────────────────┘
"""

from __future__ import annotations

import time
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Header, Markdown, Static, TextArea

from agent.core import Agent
from agent.streaming import StreamEventType
from agent.tools.adapters.browser_harness import BrowserHarnessAdapter


class ThinkingBlock(Static):
    """Collapsible thinking block. Ctrl+T to toggle."""

    expanded = reactive(True)

    def __init__(self):
        super().__init__("", classes="think")
        self._text = ""

    def feed(self, chunk: str) -> None:
        self._text += chunk
        self._redraw()

    def toggle(self) -> None:
        self.expanded = not self.expanded
        self._redraw()

    def _redraw(self) -> None:
        if self.expanded:
            w = self.size.width - 4 if self.size.width > 10 else 76
            box_w = min(w, 80)
            lines = ["┌─ Thinking " + "─" * (box_w - 12) + "┐"]
            for line in self._text.split("\n")[-20:]:
                line = line[:box_w - 2]
                lines.append(f"│ {line}".ljust(box_w + 1) + "│")
            lines.append("└" + "─" * (box_w - 1) + "┘")
            self.update("\n".join(lines))
        else:
            n = len(self._text)
            self.update(f"  · Thinking... ({n} chars)  [dim]Ctrl+T to expand[/]")


class ResponseBlock(Markdown):
    """A markdown response block with raw text tracking."""

    def __init__(self, text: str = ""):
        super().__init__(text or " ", classes="resp")
        self.raw_text = text


class AgentTui(App):
    """Textual TUI for therain2020-agent."""

    CSS = """
    #transcript {
        overflow-y: auto;
        padding: 1 2;
    }
    .think {
        color: grey;
        margin: 1 0;
        height: auto;
    }
    .tool {
        color: grey;
        height: 1;
        padding: 0 2;
    }
    .resp {
        margin: 1 0;
    }
    #bottom {
        dock: bottom;
        height: auto;
        max-height: 30%;
        background: $surface;
        border-top: solid $primary-darken-3;
    }
    #prompt {
        height: auto;
        min-height: 3;
        max-height: 12;
        padding: 0 1;
        border: none;
    }
    #status {
        height: 1;
        padding: 0 1;
        color: $text-disabled;
    }
    """

    BINDINGS = [
        Binding("ctrl+t", "toggle_thinking", "Think"),
        Binding("ctrl+c", "quit", "Exit"),
        Binding("enter", "submit", "Send", priority=True),
        Binding("ctrl+enter", "newline", "Newline", show=False),
        Binding("up", "history_up", "Hist↑", show=False, priority=True),
        Binding("down", "history_down", "Hist↓", show=False, priority=True),
    ]

    def __init__(self, provider=None):
        super().__init__()
        self._provider_arg = provider
        self._agent: Agent | None = None
        self._history: list[str] = []
        self._hpos: int = -1
        self._think: ThinkingBlock | None = None
        self._resp: ResponseBlock | None = None
        self._tools: list[Static] = []
        self._busy = False
        self._auto_scroll = True
        self._model = "none"
        self._conversation: str = ""  # accumulated context across turns

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield VerticalScroll(id="transcript")
        with Container(id="bottom"):
            yield TextArea(id="prompt")
            yield Static(id="status")

    def on_mount(self) -> None:
        self.query_one(Header).tall = False

        # Dirs
        d = Path.home() / ".therain2020-agent"
        for sub in ["memory", "tools", "tools/.generated", "dont-do"]:
            (d / sub).mkdir(parents=True, exist_ok=True)

        self._agent = Agent()
        self._agent.setup()

        from agent.cli.autodetect import detect_from_env
        prov, cfg, src = detect_from_env()
        if prov:
            self._agent.set_provider(prov, cfg)
            self._model = cfg.model if cfg else "?"
        else:
            self._model = "none"

        try:
            BrowserHarnessAdapter(self._agent.registry).register()
        except Exception:
            pass

        self.title = "therain2020-agent"
        self.sub_title = f"v0.7.1  [{self._model}]"

        self._set_status(f"[dim]{self._model}[/] | Ctrl+T:think | /help | Ctrl+C:exit")

        self._echo(f"[bold]therain2020-agent[/] v0.7.1 — {self._model} ({src})")
        self._echo("[dim]Type a task or /help.[/]")
        self.query_one("#prompt", TextArea).focus()

    # ── transcript helpers ──

    def _echo(self, text: str) -> None:
        w = Static(text)
        self.query_one("#transcript", VerticalScroll).mount(w)
        if self._auto_scroll:
            w.scroll_visible()

    def _mount(self, widget) -> None:
        self.query_one("#transcript", VerticalScroll).mount(widget)
        if self._auto_scroll:
            widget.scroll_visible()

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    # ── scroll tracking ──

    def on_vertical_scroll_scrolled(self, event) -> None:
        vs = self.query_one("#transcript", VerticalScroll)
        at_bottom = vs.scroll_offset.y >= (vs.max_scroll_y - 3) if vs.max_scroll_y > 0 else True
        self._auto_scroll = at_bottom

    # ── input ──

    def action_newline(self) -> None:
        """Insert a newline (Ctrl+Enter)."""
        ta = self.query_one("#prompt", TextArea)
        ta.insert("\n")

    def action_submit(self) -> None:
        ta = self.query_one("#prompt", TextArea)
        text = ta.text.strip()
        if not text or self._busy:
            return
        ta.clear()

        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._hpos = len(self._history)

        if text.startswith("/"):
            self._slash(text)
            return

        self._echo(f"\n[bold]> {text}[/]")
        self._run(text)

    def action_history_up(self) -> None:
        if not self._history:
            return
        ta = self.query_one("#prompt", TextArea)
        if self._hpos == len(self._history):
            self._hpos = len(self._history) - 1
        elif self._hpos > 0:
            self._hpos -= 1
        ta.text = self._history[self._hpos]

    def action_history_down(self) -> None:
        ta = self.query_one("#prompt", TextArea)
        if self._hpos < len(self._history) - 1:
            self._hpos += 1
            ta.text = self._history[self._hpos]
        else:
            self._hpos = len(self._history)
            ta.text = ""

    # ── slash ──

    def _slash(self, text: str) -> None:
        parts = text.strip().lower().split()
        cmd = parts[0]
        if cmd == "/help":
            self._echo("[dim]/help /clear /tools /skills /think /exit[/]")
        elif cmd == "/clear":
            self.query_one("#transcript", VerticalScroll).remove_children()
            self._conversation = ""
        elif cmd == "/tools":
            tools = self._agent.registry.list_all()
            for t in sorted(tools, key=lambda x: x.name):
                caps = ", ".join(c.name for c in t.capabilities)
                self._echo(f"  {t.name} [dim]{caps}[/]")
        elif cmd == "/skills":
            try:
                skills = self._agent.skill_repo.get_active(limit=20)
                for s in skills:
                    self._echo(f"  {s.name} [dim]×{s.uses} score={s.score}[/]")
            except Exception:
                self._echo("[dim]Skills unavailable.[/]")
        elif cmd == "/think":
            if self._think:
                self._think.toggle()
        elif cmd == "/exit":
            self.exit()
        else:
            self._echo(f"[dim]Unknown: {cmd}. Type /help.[/]")

    # ── task runner ──

    @work(thread=False, exclusive=True)
    async def _run(self, task: str) -> None:
        self._busy = True
        self._think = None
        self._resp = None
        self._tools.clear()
        self._set_status(f"[dim]{self._model}[/] | [yellow]Thinking...[/]")
        t0 = time.time()

        # Inject conversation context from previous turns
        ctx = ""
        if self._conversation:
            ctx = f"\n\nPrevious conversation:\n{self._conversation[-3000:]}"
        full_task = task + ctx

        # Accumulate this turn
        self._conversation += f"\nUser: {task}"

        try:
            if self._agent.supports_structured_stream():
                async for ev in self._agent.run_stream(full_task):
                    if ev.type == StreamEventType.THINKING:
                        self._on_think(ev.content)
                    elif ev.type == StreamEventType.TEXT:
                        self._conversation += f"\nAssistant: {ev.content[:500]}"
                        self._on_text(ev.content)
                    elif ev.type == StreamEventType.TOOL_START:
                        self._on_tool_start(ev.tool_name, ev.capability)
                    elif ev.type == StreamEventType.TOOL_RESULT:
                        self._on_tool_done(ev.tool_name, ev.capability, ev.ok)
                    elif ev.type == StreamEventType.ERROR:
                        self._echo(f"[red]Error: {ev.content}[/]")
                    elif ev.type == StreamEventType.DONE:
                        dt = round(time.time() - t0, 1)
                        if ev.success:
                            self._echo(f"[green][OK][/] {ev.steps} steps in {dt}s")
                        else:
                            self._echo(f"[red][FAILED][/] {ev.error_msg}")
            else:
                self._echo("[dim]  …[/]")
                r = await self._agent.run(task)
                dt = round(time.time() - t0, 1)
                self._echo(f"[green][OK][/] {r['steps']} steps in {dt}s" if r["success"]
                           else f"[red][FAILED][/] {r.get('error', '')}")
        except Exception as e:
            self._echo(f"[red]Error: {e}[/]")
        finally:
            self._busy = False
            self._set_status(f"[dim]{self._model}[/] | Ctrl+T:think | /help | Ctrl+C:exit")
            self.query_one("#prompt", TextArea).focus()

    def _on_think(self, chunk: str) -> None:
        if self._think is None:
            self._think = ThinkingBlock()
            self._mount(self._think)
        self._think.feed(chunk)

    def _on_text(self, chunk: str) -> None:
        if self._resp is None:
            self._resp = ResponseBlock(chunk)
            self._mount(self._resp)
        else:
            self._resp.raw_text += chunk
            try:
                self._resp.update(self._resp.raw_text)
            except Exception:
                pass

    def _on_tool_start(self, name: str, cap: str) -> None:
        w = Static(f"  → {name}.{cap}  ", classes="tool")
        self._mount(w)
        self._tools.append(w)

    def _on_tool_done(self, name: str, cap: str, ok: bool) -> None:
        mark = "[green]✓[/]" if ok else "[yellow]⚠[/]"
        for w in reversed(self._tools):
            if name in str(w.renderable) and cap in str(w.renderable):
                w.update(f"  → {name}.{cap}  {mark}")
                break

    def action_toggle_thinking(self) -> None:
        if self._think:
            self._think.toggle()
