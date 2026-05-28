"""Tests for interactive REPL."""

from agent.cli.repl import AgentRepl, _bold, _dim, _hint, _ok, _warn


def _make_agent(tmp_path):
    from agent.core import Agent
    return Agent(config_dict={
        "agent": {"name": "test", "max_loop_iterations": 3},
        "tools": {"scan_paths": [str(tmp_path / "tools")]},
        "security": {"dont_do_paths": [str(tmp_path / "dont-do")]},
        "memory": {"path": str(tmp_path / "memory" / "agent.db")},
        "skills": {"path": str(tmp_path / "skills.db")},
    })


class TestReplStyling:
    def test_bold(self):
        assert _bold("test")

    def test_dim(self):
        assert _dim("test")

    def test_hint(self):
        assert _hint("test")

    def test_ok(self):
        assert _ok("test")

    def test_warn(self):
        assert _warn("test")


class TestAgentRepl:
    def test_init(self, tmp_path):
        agent = _make_agent(tmp_path)
        repl = AgentRepl(agent)
        assert repl.turn == 0
        assert repl.conversation == []
        assert repl._mode == "auto"
        assert repl._running

    def test_slash_mode_switch(self, tmp_path):
        agent = _make_agent(tmp_path)
        repl = AgentRepl(agent)
        repl._handle_slash("/mode todo")
        assert repl._mode == "todo"
        repl._handle_slash("/mode goal")
        assert repl._mode == "goal"
        repl._handle_slash("/mode auto")
        assert repl._mode == "auto"

    def test_slash_clear(self, tmp_path):
        agent = _make_agent(tmp_path)
        repl = AgentRepl(agent)
        repl.conversation = [{"role": "user", "content": "test"}]
        repl._handle_slash("/clear")
        assert repl.conversation == []

    def test_slash_help(self, tmp_path):
        agent = _make_agent(tmp_path)
        repl = AgentRepl(agent)
        repl._handle_slash("/help")
        assert repl._running

    def test_slash_exit(self, tmp_path):
        agent = _make_agent(tmp_path)
        repl = AgentRepl(agent)
        repl._handle_slash("/exit")
        assert not repl._running

    def test_progress_callback_set_and_cleared(self, tmp_path):
        agent = _make_agent(tmp_path)
        callback_calls = []
        agent.set_progress_callback(lambda e: callback_calls.append(e))
        agent._emit_progress({"type": "thinking"})
        assert len(callback_calls) == 1
        assert callback_calls[0]["type"] == "thinking"
