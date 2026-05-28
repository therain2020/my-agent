"""Textual TUI — modeled on Claude Code's terminal interface.

Key patterns replicated from Claude Code's Ink/React TUI:
- Simple `> ` prompt with inline input, no heavy box borders
- Subtle dimmed spinner during thinking
- Thinking blocks: dim border, collapsible (Ctrl+T)
- Tool calls: compact single line with status
- Response: rendered as Markdown, natural flow
- Status bar: model + hints, minimal
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

# ── widgets ──


class ThinkBlock(Static):
    """Collapsible thinking block. Like Claude Code's AssistantThinkingMessage."""

    expanded = reactive(True)

    def __init__(self):
        super().__init__("", classes="think")
        self._buf = ""

    def feed(self, s: str) -> None:
        self._buf += s
        self._draw()

    def flip(self) -> None:
        self.expanded = not self.expanded
        self._draw()

    def _draw(self) -> None:
        if not self._buf:
            return
        if self.expanded:
            self.update(f"[dim]● Thinking[/]\n[dim]{self._buf[-2000:]}[/]")
        else:
            self.update(f"[dim]● Thinking... ({len(self._buf)} chars)  Ctrl+O to expand[/]")


class RespBlock(Markdown):
    """Streaming response — incremental markdown rendering."""

    def __init__(self):
        super().__init__("", classes="resp")
        self.raw = ""

    def feed(self, s: str) -> None:
        self.raw += s
        try:
            self.update(self.raw)
        except Exception:
            pass


class ToolLine(Static):
    """Compact tool call indicator."""

    def __init__(self, tool: str, cap: str):
        super().__init__(f"  [dim]⏳ {tool}.{cap}[/]", classes="tool")
        self._tool = tool
        self._cap = cap

    def mark(self, ok: bool = True) -> None:
        s = "[green]✓[/]" if ok else "[yellow]⚠[/]"
        self.update(f"  {s} [dim]{self._tool}.{self._cap}[/]")


# ── app ──


class AgentTui(App):
    """Claude Code-style terminal interface for therain2020-agent."""

    CSS = """
    #transcript {
        padding: 0 2 1 2;
        overflow-y: auto;
    }
    .think {
        margin: 1 2;
        height: auto;
    }
    .tool {
        margin: 0 2;
        height: 1;
    }
    .resp {
        margin: 1 0;
        height: auto;
    }
    #bottom {
        dock: bottom;
        height: auto;
        max-height: 35%;
        background: $surface;
        border-top: solid $primary-darken-3;
        padding: 0 1;
    }
    #status {
        height: 1;
        color: $text-disabled;
    }
    #prompt {
        height: auto;
        min-height: 1;
        max-height: 8;
        border: none;
        padding: 0;
    }
    TextArea:focus {
        border: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+o", "toggle_thinking", "Think"),
        Binding("ctrl+c", "quit", "Exit"),
        Binding("enter", "submit", "Send", priority=True),
        Binding("ctrl+enter", "newline", "NL", show=False),
        Binding("up", "history_up", "↑", show=False, priority=True),
        Binding("down", "history_down", "↓", show=False, priority=True),
    ]

    def __init__(self, provider=None):
        super().__init__()
        self._agent: Agent | None = None
        self._hist: list[str] = []
        self._hp: int = -1
        self._busy = False
        self._scroll = True
        self._model = "?"
        self._ctx = ""          # conversation context
        self._think: ThinkBlock | None = None
        self._resp: RespBlock | None = None
        self._tools: list[ToolLine] = []

    # ── compose / mount ──

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield VerticalScroll(id="transcript")
        with Container(id="bottom"):
            yield TextArea(id="prompt")
            yield Static(id="status")

    def on_mount(self) -> None:
        self.query_one(Header).tall = False
        d = Path.home() / ".therain2020-agent"
        for sub in ["memory", "tools", "tools/.generated", "dont-do"]:
            (d / sub).mkdir(parents=True, exist_ok=True)

        self._agent = Agent()
        self._agent.setup()

        try:
            BrowserHarnessAdapter(self._agent.registry).register()
        except Exception:
            pass

        from agent.cli.autodetect import detect_from_env
        p, c, src = detect_from_env()
        if p:
            self._agent.set_provider(p, c)
            self._model = c.model if c else "?"
        self.title = "therain2020-agent"
        self.sub_title = f"[{self._model}]"
        self._status(f"{self._model}  |  Ctrl+O think  |  /help  |  Ctrl+C exit")
        self._say(f"[bold]therain2020-agent[/] — {self._model} [dim]({src})[/]")
        self._say("[dim]Ask anything. /help for commands.[/]")
        self.query_one("#prompt", TextArea).focus()

    # ── transcript ──

    def _say(self, text: str) -> None:
        w = Static(text)
        self.query_one("#transcript", VerticalScroll).mount(w)
        if self._scroll:
            w.scroll_visible()

    def _put(self, w) -> None:
        self.query_one("#transcript", VerticalScroll).mount(w)
        if self._scroll:
            w.scroll_visible()

    def _status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def on_vertical_scroll_scrolled(self, _) -> None:
        vs = self.query_one("#transcript", VerticalScroll)
        bottom = vs.scroll_offset.y >= (vs.max_scroll_y - 3) if vs.max_scroll_y > 0 else True
        self._scroll = bottom

    # ── input ──

    def action_newline(self) -> None:
        self.query_one("#prompt", TextArea).insert("\n")

    def action_submit(self) -> None:
        ta = self.query_one("#prompt", TextArea)
        t = ta.text.strip()
        if not t or self._busy:
            return
        ta.clear()
        if not self._hist or self._hist[-1] != t:
            self._hist.append(t)
        self._hp = len(self._hist)
        if t.startswith("/"):
            self._cmd(t)
            return
        self._say(f"\n[bold]> {t}[/]")
        self._run(t)

    def action_history_up(self) -> None:
        if not self._hist:
            return
        ta = self.query_one("#prompt", TextArea)
        if self._hp == len(self._hist):
            self._hp = len(self._hist) - 1
        elif self._hp > 0:
            self._hp -= 1
        ta.text = self._hist[self._hp]

    def action_history_down(self) -> None:
        ta = self.query_one("#prompt", TextArea)
        if self._hp < len(self._hist) - 1:
            self._hp += 1
            ta.text = self._hist[self._hp]
        else:
            self._hp = len(self._hist)
            ta.text = ""

    def action_toggle_thinking(self) -> None:
        if self._think:
            self._think.flip()

    # ── commands ──

    def _cmd(self, text: str) -> None:
        p = text.strip().lower().split()
        c = p[0]
        if c == "/help":
            self._say("[dim]/help /clear /tools /skills /think /exit[/]")
        elif c == "/clear":
            self.query_one("#transcript", VerticalScroll).remove_children()
            self._ctx = ""
        elif c == "/tools":
            for t in sorted(self._agent.registry.list_all(), key=lambda x: x.name):
                caps = ", ".join(c.name for c in t.capabilities)
                self._say(f"  [bold]{t.name}[/] [dim]{caps}[/]")
        elif c == "/skills":
            try:
                for s in self._agent.skill_repo.get_active(20):
                    self._say(f"  {s.name} [dim]×{s.uses} s={s.score}[/]")
            except Exception:
                self._say("[dim]unavailable[/]")
        elif c == "/think":
            if self._think:
                self._think.flip()
        elif c == "/exit":
            self.exit()
        else:
            self._say(f"[dim]? {c}[/]")

    # ── run ──

    @work(thread=False, exclusive=True)
    async def _run(self, task: str) -> None:
        self._busy = True
        self._think = None
        self._resp = None
        self._tools.clear()
        self._status(f"{self._model}  |  [yellow]thinking…[/]")
        t0 = time.time()

        ctx = f"\n\n[context]\n{self._ctx[-3000:]}" if self._ctx else ""
        self._ctx += f"\nUser: {task}"

        try:
            if self._agent.supports_structured_stream():
                async for ev in self._agent.run_stream(task + ctx):
                    t = ev.type
                    if t == StreamEventType.THINKING:
                        if self._think is None:
                            self._think = ThinkBlock()
                            self._put(self._think)
                        self._think.feed(ev.content)
                    elif t == StreamEventType.TEXT:
                        self._ctx += ev.content[:500]
                        if self._resp is None:
                            self._resp = RespBlock()
                            self._put(self._resp)
                        self._resp.feed(ev.content)
                    elif t == StreamEventType.TOOL_START:
                        tl = ToolLine(ev.tool_name, ev.capability)
                        self._put(tl)
                        self._tools.append(tl)
                    elif t == StreamEventType.TOOL_RESULT:
                        for tl in reversed(self._tools):
                            if ev.tool_name in tl._tool and ev.capability in tl._cap:
                                tl.mark(ev.ok)
                                break
                    elif t == StreamEventType.ERROR:
                        self._say(f"[red]Error: {ev.content}[/]")
                    elif t == StreamEventType.DONE:
                        d = round(time.time() - t0, 1)
                        self._say(
                            f"[green]✓[/] {ev.steps} steps in {d}s"
                            if ev.success else
                            f"[red]✗[/] {ev.error_msg}"
                        )
            else:
                r = await self._agent.run(task + ctx)
                d = round(time.time() - t0, 1)
                self._say(
                    f"[green]✓[/] {r['steps']} steps in {d}s"
                    if r["success"] else
                    f"[red]✗[/] {r.get('error', '')}"
                )
        except Exception as e:
            self._say(f"[red]Error: {e}[/]")
        finally:
            self._busy = False
            self._status(f"{self._model}  |  Ctrl+O think  |  /help  |  Ctrl+C exit")
            self.query_one("#prompt", TextArea).focus()
