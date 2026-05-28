"""Tests for run.py — CLI entry point."""

import sys
from io import StringIO
from unittest.mock import patch

from therain2020.run import cli


def test_help_flag():
    stdout = StringIO()
    with patch.object(sys, "argv", ["therain2020", "--help"]), \
         patch("sys.stdout", stdout):
        cli()
    assert "Usage" in stdout.getvalue()


def test_no_args_tty_exits():
    mock_stdin = StringIO("")
    mock_stdin.isatty = lambda: True
    with patch.object(sys, "argv", ["therain2020"]), \
         patch("sys.stdin", mock_stdin):
        try:
            cli()
        except SystemExit as e:
            assert e.code == 1
        else:
            raise AssertionError("should have exited")


def test_pipe_task(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    mock_stdin = StringIO("hello world")
    mock_stdin.isatty = lambda: False
    with patch.object(sys, "argv", ["therain2020"]), \
         patch("sys.stdin", mock_stdin), \
         patch("therain2020.run._run_task") as mock_run:
        cli()
    mock_run.assert_called_once()


def test_arg_task(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch.object(sys, "argv", ["therain2020", "say", "hello"]), \
         patch("therain2020.run._run_task") as mock_run:
        cli()
    mock_run.assert_called_once()


def test_repl_flag():
    with patch.object(sys, "argv", ["therain2020", "--repl"]), \
         patch("therain2020.run._run_repl") as mock_repl:
        cli()
    mock_repl.assert_called_once()
