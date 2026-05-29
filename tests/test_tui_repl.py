"""Tests for cli/app.py — Repl class."""


from therain2020.cli.app import Repl


def test_repl_creation():
    repl = Repl()
    assert repl.turn == 0
    assert not repl._running
    assert not repl._thinking_visible


def test_repl_handle_exit():
    repl = Repl()
    repl._running = True
    repl._handle_slash("/exit")
    assert not repl._running


def test_repl_handle_help(capsys):
    repl = Repl()
    repl._handle_slash("/help")
    captured = capsys.readouterr()
    assert "help" in captured.out.lower()


def test_repl_handle_quit():
    repl = Repl()
    repl._running = True
    repl._handle_slash("/quit")
    assert not repl._running


def test_repl_toggle_think():
    repl = Repl()
    repl._handle_slash("/think")
    assert repl._thinking_visible
    repl._handle_slash("/think")
    assert not repl._thinking_visible
