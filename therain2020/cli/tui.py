"""TUI components migrated from agent/cli/tui/app.py.

Adapted to use the new therain2020.agent.run_stream() interface.
Minimal dependencies: Textual + Rich.
"""

from __future__ import annotations

import time
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Header, Markdown, Static, TextArea

from ..agent import run_stream
from ..cli.streaming import StreamEventType
from ..session import create_session


class ThinkBlock(Static):
    """Collapsible thinking/reasoning block."""

    def __init__(self):
        super().__init__("", classes="think collapsed")
        self._raw = ""

    def feed(self, s: str):
        self._raw += s
        self.update(self._raw[-3000:] if len(self._raw) > 3000 else self._raw)

    def flip(self):
        if "collapsed" in self.classes:
            self.classes = set(self.classes) - {"collapsed"}
        else:
            self.classes = set(self.classes) | {"collapsed"}


class RespBlock(Markdown):
    """Streaming markdown response block."""

    def __init__(self):
        super().__init__("")
        self.raw = ""

    def feed(self, s: str):
        self.raw += s
        self.update(self.raw)


class ToolLine(Static):
    """Compact tool call indicator."""

    def __init__(self, name: str, capability: str):
        super().__init__(f"  … {name}.{capability}", classes="tool")
        self._name = name

    def mark(self, ok: bool):
        prefix = "✓" if ok else "⚠"
        cls = "tool-ok" if ok else "tool-warn"
        self.update(f"  {prefix} {self._name}")
        self.classes = set(self.classes) | {cls}


class AgentTui(App):
    """Textual TUI for therain2020 agent."""

    CSS = """
    #transcript { overflow-y: auto; }
    #transcript > * { margin-bottom: 1; }
    .think { color: $text-muted; }
    .think.collapsed { height: 1; overflow: hidden; }
    .tool { color: $text-muted; }
    .tool-ok  { color: $success; }
    .tool-warn  { color: $warning; }
    .resp { margin-top: 1; }
    #bottom { dock: bottom; border-top: solid $primary; padding: 1; }
    #prompt { height: auto; max-height: 8; }
    #status { height: 1; color: $text-muted; }
    """

    BINDINGS = [
        Binding("ctrl+o", "toggle_thinking", "Toggle Thinking"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("enter", "submit", "Submit", priority=True),
        Binding("ctrl+enter", "newline", "Newline"),
        Binding("up", "history_up", "History Up"),
        Binding("down", "history_down", "History Down"),
    ]

    def __init__(self):
        super().__init__()
        self._hist: list[str] = []
        self._hp: int = 0
        self._busy: bool = False
        self._think: ThinkBlock | None = None
        self._resp: RespBlock | None = None
        self._tools: dict[str, ToolLine] = {}
        self._ctx: str = ""
        home = Path.home() / ".therain2020-agent"
        home.mkdir(parents=True, exist_ok=True)

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="transcript")
        with Container(id="bottom"):
            yield TextArea(id="prompt", tab_behavior="indent")
            yield Static("Ready — Ctrl+O toggle thinking, Ctrl+C quit", id="status")

    def on_mount(self):
        from ..provider import detect_providers
        self.title = "therain2020 agent"
        providers = detect_providers()
        model = providers[0].model if providers else "no provider"
        self._status(f"Model: {model}")
        self._say(f"# therain2020 v0.8.0\nModel: **{model}**\nType a task to begin.")

    # -- transcript helpers -----------------------------------------------

    def _say(self, text: str):
        w = Static(text)
        self.query_one("#transcript").mount(w)
        self._scroll_end()

    def _put(self, w):
        self.query_one("#transcript").mount(w)
        self._scroll_end()

    def _status(self, text: str):
        self.query_one("#status").update(text)

    def _scroll_end(self):
        try:
            self.query_one("#transcript").scroll_end(animate=False)
        except Exception:
            pass

    # -- input handling ---------------------------------------------------

    def action_newline(self):
        self.query_one("#prompt").insert("\n")

    @work(thread=False, exclusive=True)
    async def action_submit(self):
        if self._busy:
            return
        prompt = self.query_one("#prompt")
        text = prompt.text.strip()
        if not text:
            return
        prompt.clear()
        self._hist.append(text)
        self._hp = len(self._hist)

        # slash commands
        if text.startswith("/"):
            await self._handle_slash(text)
            return

        await self._run(text)

    def action_history_up(self):
        if not self._hist:
            return
        self._hp = max(0, self._hp - 1)
        self.query_one("#prompt").text = self._hist[self._hp]

    def action_history_down(self):
        if not self._hist:
            return
        self._hp = min(len(self._hist), self._hp + 1)
        if self._hp >= len(self._hist):
            self.query_one("#prompt").text = ""
        else:
            self.query_one("#prompt").text = self._hist[self._hp]

    def action_toggle_thinking(self):
        if self._think:
            self._think.flip()

    # -- slash commands ---------------------------------------------------

    async def _handle_slash(self, cmd: str):
        parts = cmd.split()
        op = parts[0].lower()
        if op in ("/exit", "/quit"):
            self.exit()
        elif op == "/help":
            self._say("**Commands:** /help /clear /tools /think /exit")
        elif op == "/clear":
            ts = self.query_one("#transcript")
            for c in list(ts.children):
                if c.id not in ("bottom",):
                    c.remove()
        elif op == "/tools":
            session = create_session(task="")
            tools = session.tools.list_all()
            names = ", ".join(t.name for t in tools)
            self._say(f"**Tools:** {names}")
            session.memory.close()
        elif op == "/think":
            if self._think:
                self._think.flip()
        else:
            self._say(f"Unknown command: {op}")

    # -- task execution ---------------------------------------------------

    async def _run(self, task: str):
        self._busy = True
        self._think = ThinkBlock()
        self._resp = RespBlock()
        self._tools = {}
        self._put(self._think)
        self._put(self._resp)

        t0 = time.time()
        steps = 0
        tools_used: list[str] = []

        try:
            # Build conversation context from transcript
            ctx_task = task
            if self._ctx:
                ctx_task = f"Context: {self._ctx[-3000:]}\nTask: {task}"

            session = create_session(task=ctx_task)
            tool_names = [t.name for t in session.tools.list_all()]
            self._status(f"Running... tools: {tool_names}")

            async for event in run_stream(ctx_task, session):
                if event.type == StreamEventType.THINKING:
                    self._think.feed(event.content)
                elif event.type == StreamEventType.TEXT:
                    self._resp.feed(event.content)
                elif event.type == StreamEventType.TOOL_START:
                    tl = ToolLine(event.tool_name, event.capability)
                    self._tools[event.tool_name] = tl
                    self._put(tl)
                elif event.type == StreamEventType.TOOL_RESULT:
                    if event.tool_name in self._tools:
                        self._tools[event.tool_name].mark(event.ok)
                    tools_used.append(event.tool_name)
                elif event.type == StreamEventType.ERROR:
                    self._say(f"**Error:** {event.error_msg}")
                elif event.type == StreamEventType.DONE:
                    steps = event.steps
                    tools_used = event.tools_used

            session.memory.close()

        except Exception as e:
            self._say(f"**Error:** {e}")
        finally:
            self._busy = False
            elapsed = time.time() - t0
            self._status(f"Done — {steps} steps, {elapsed:.1f}s, tools: {tools_used or 'none'}")


def run_tui():
    AgentTui().run()
