"""Interactive REPL — conversation-style agent UX like Claude Code.

Keeps the agent alive across turns. Each user message continues
the same session with full context: memory, skills, tool evolution.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import click

from agent.core import Agent
from agent.tools.adapters.browser_harness import BrowserHarnessAdapter

# ── terminal helpers ──


def _dim(text: str) -> str:
    return click.style(text, dim=True)


def _bold(text: str) -> str:
    return click.style(text, bold=True)


def _ok(text: str) -> str:
    return click.style(text, fg="green")


def _warn(text: str) -> str:
    return click.style(text, fg="yellow")


def _err(text: str) -> str:
    return click.style(text, fg="red")


def _hint(text: str) -> str:
    return click.style(text, fg="cyan")


LOGO = r"""
  {} v{}
  Type /help for commands, Ctrl+C or /exit to quit.
""".format(
    _bold("therain2020-agent"),
    "0.6.0",
)

HELP_TEXT = f"""
{_bold("Slash Commands")}
  {_hint("/help")}       Show this message
  {_hint("/clear")}      Clear conversation context (keep memory)
  {_hint("/tools")}      List available tools
  {_hint("/mode")}       Show or switch execution mode (todo/goal)
  {_hint("/history")}    Show recent episode history
  {_hint("/skills")}     Show learned skills
  {_hint("/exit")}       Exit (Ctrl+C or Ctrl+D also works)

{_bold("Tips")}
  Just type your task — the agent figures out how to do it.
  Each message continues the same session. Context persists.
"""


# ── REPL ──


class AgentRepl:
    """Interactive REPL for therain2020-agent.

    One Agent instance lives for the entire session.
    """

    def __init__(self, agent: Agent):
        self.agent = agent
        self.turn = 0
        self.conversation: list[dict] = []  # [{role, content, tools, duration}]
        self._mode = "auto"  # auto | todo | goal
        self._running = True

    async def start(self) -> None:
        """Main REPL loop."""
        self._setup_readline()
        click.echo(LOGO)

        # Quick check: has a provider?
        if self.agent._provider is None:
            click.echo(
                _warn("\nNo LLM provider configured.\n")
                + _dim("Run outside the REPL: therain2020-agent provider add ...\n")
            )

        while self._running:
            try:
                raw = await self._prompt()
            except (KeyboardInterrupt, EOFError):
                click.echo("\n")
                break

            if raw is None:
                break
            if not raw.strip():
                continue

            # Slash commands
            if raw.startswith("/"):
                self._handle_slash(raw)
                continue

            # Execute
            self.turn += 1
            await self._execute(raw)

        self._shutdown()

    async def _prompt(self) -> str | None:
        """Show prompt and get user input."""
        mode_label = _dim(f"[{self._mode}]") if self._mode != "auto" else ""
        prompt = f"\n{mode_label} {_bold('>')} " if mode_label else f"\n{_bold('>')} "
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: input(prompt))
        except (KeyboardInterrupt, EOFError):
            return None

    async def _execute(self, task: str) -> None:
        """Execute a user task turn with streaming progress."""
        click.echo()

        mode = self._mode
        if mode == "auto":
            mode = "goal" if len(task) > 30 else "todo"

        start = time.time()
        self._thinking_printed = False

        def on_progress(event: dict) -> None:
            etype = event.get("type", "")
            if etype == "thinking":
                if not self._thinking_printed:
                    click.echo(_dim("  Thinking..."), nl=False)
                    self._thinking_printed = True
            elif etype == "tool_start":
                if self._thinking_printed:
                    click.echo("")  # end the "Thinking..." line
                    self._thinking_printed = False
                click.echo(
                    f"  {_dim('→')} {_hint(event['tool'])}.{event['capability']}  ",
                    nl=False,
                )
            elif etype == "tool_result":
                ok = event.get("ok", True)
                mark = _ok("✓") if ok else _warn("⚠")
                click.echo(mark)
            elif etype == "done":
                if self._thinking_printed:
                    click.echo("")

        self.agent.set_progress_callback(on_progress)

        try:
            if mode == "goal":
                result = await self.agent.goal_run(task)
            else:
                result = await self.agent.run(task)
        except KeyboardInterrupt:
            click.echo(_warn("\nInterrupted."))
            return
        except Exception as e:
            click.echo(_err(f"\nError: {e}"))
            return
        finally:
            self.agent.set_progress_callback(None)

        duration = round(time.time() - start, 1)
        self.conversation.append({
            "role": "user",
            "content": task[:200],
            "tools": result.get("tools_used", []),
            "duration": duration,
        })

        # Print result
        click.echo()
        if result["success"]:
            summary = _ok("[OK]") + f" {result['steps']} steps in {duration}s"
            click.echo(summary)
        else:
            click.echo(_err("[FAILED]") + f" {result.get('error', 'unknown')}")
        if result.get("tools_used"):
            click.echo(_dim(f"     tools: {', '.join(result['tools_used'])}"))

    # ── slash commands ──

    def _handle_slash(self, raw: str) -> None:
        cmd = raw.strip().lower()
        parts = cmd.split()

        if parts[0] == "/help":
            click.echo(HELP_TEXT)

        elif parts[0] == "/clear":
            size = len(self.conversation)
            self.conversation.clear()
            click.echo(_ok(f"Cleared {size} conversation turns (memory + skills preserved)."))

        elif parts[0] == "/tools":
            tools = self.agent.registry.list_all()
            if not tools:
                click.echo(_dim("No tools registered."))
                return
            click.echo(_bold(f"\n{len(tools)} tools:"))
            for t in sorted(tools, key=lambda x: x.name):
                caps = ", ".join(c.name for c in t.capabilities)
                click.echo(f"  {_hint(t.name):40s} {_dim(caps)}")

        elif parts[0] == "/mode":
            if len(parts) > 1 and parts[1] in ("todo", "goal", "auto"):
                self._mode = parts[1]
                click.echo(_ok(f"Mode: {self._mode}"))
            else:
                click.echo(f"Current mode: {_bold(self._mode)}")
                click.echo(_dim("  /mode todo   — best for clear acceptance criteria"))
                click.echo(_dim("  /mode goal   — best for open-ended objectives"))
                click.echo(_dim("  /mode auto   — auto-detect (default)"))

        elif parts[0] == "/history":
            if not self.conversation:
                click.echo(_dim("No conversation history yet."))
                return
            click.echo(_bold(f"\n{len(self.conversation)} turns:"))
            for i, entry in enumerate(self.conversation, 1):
                tools_str = ", ".join(entry["tools"]) if entry["tools"] else "none"
                click.echo(
                    f"  {i}. {_dim(entry['content'][:100])}  "
                    f"({entry['duration']}s, {tools_str})"
                )

        elif parts[0] == "/skills":
            try:
                skills = self.agent.skill_repo.get_active(limit=20)
                if not skills:
                    click.echo(_dim("No skills learned yet. Complete some tasks first."))
                    return
                click.echo(_bold(f"\n{len(skills)} active skills:"))
                for s in skills:
                    rating = _ok(f"{s.success_rate:.0%}") if s.success_rate > 0.7 else _warn(f"{s.success_rate:.0%}")
                    click.echo(f"  {_hint(s.name):30s} {rating}  uses={s.uses}  score={s.score}")
            except Exception:
                click.echo(_dim("Skill repository not available."))

        elif parts[0] in ("/exit", "/quit"):
            self._running = False

        else:
            click.echo(_dim(f"Unknown command: {cmd}. Type /help."))

    # ── setup / teardown ──

    @staticmethod
    def _setup_readline() -> None:
        """Enable readline history if available."""
        try:
            import readline
            hist_file = Path.home() / ".therain2020-agent-history"
            if hist_file.exists():
                readline.read_history_file(str(hist_file))
            import atexit
            atexit.register(lambda: readline.write_history_file(str(hist_file)))
        except Exception:
            pass  # readline not available (Windows without pyreadline)

    def _shutdown(self) -> None:
        click.echo(_dim("\nGoodbye."))
        try:
            self.agent.teardown()
        except Exception:
            pass


# ── entry point ──


def run_repl(provider=None) -> None:
    """Start the interactive REPL from the CLI entry point."""
    agent = Agent()
    agent.setup()

    if provider:
        from agent.cli.providers import get_provider
        prov = get_provider(provider)
        if prov:
            agent.set_provider(prov, None)

    try:
        # Register browser tools (optional — fails gracefully if no Chrome)
        adapter = BrowserHarnessAdapter(agent.registry)
        adapter.register()
    except Exception:
        pass

    repl = AgentRepl(agent)
    try:
        asyncio.run(repl.start())
    except KeyboardInterrupt:
        pass
