"""Tests for cli/repl.py — REPL instantiation and commands."""


from therain2020.cli.repl import AgentRepl


def test_repl_creation():
    repl = AgentRepl()
    assert repl.turn == 0


def test_repl_handle_exit():
    repl = AgentRepl()
    repl._running = True
    repl._handle_slash("/exit")
    assert not repl._running


def test_repl_handle_help(capsys):
    repl = AgentRepl()
    repl._handle_slash("/help")
    captured = capsys.readouterr()
    assert "help" in captured.out.lower()


def test_repl_handle_quit():
    repl = AgentRepl()
    repl._running = True
    repl._handle_slash("/quit")
    assert not repl._running


def test_repl_handle_unknown(capsys):
    repl = AgentRepl()
    repl._running = True
    repl._handle_slash("/bogus")
    captured = capsys.readouterr()
    assert "Unknown" in captured.out
