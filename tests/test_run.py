"""Tests for run.py — CLI entry point."""

import asyncio
import sys
from io import StringIO
from unittest.mock import patch

from therain2020 import run as run_mod


def test_help_flag():
    stdout = StringIO()
    with patch.object(sys, "argv", ["therain2020", "--help"]), \
         patch("sys.stdout", stdout):
        asyncio.run(run_mod.main())
    assert "Usage" in stdout.getvalue()


def test_stdin_task(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch.object(sys, "argv", ["therain2020"]), \
         patch("sys.stdin", StringIO("hello world")), \
         patch("therain2020.run.run") as mock_run:
        asyncio.run(run_mod.main())
    mock_run.assert_called_once()
    task_arg = mock_run.call_args[0][0]
    assert task_arg == "hello world"


def test_no_args_tty_exits(monkeypatch):
    mock_stdin = StringIO("")
    mock_stdin.isatty = lambda: True
    with patch.object(sys, "argv", ["therain2020"]), \
         patch("sys.stdin", mock_stdin):
        try:
            asyncio.run(run_mod.main())
        except SystemExit as e:
            assert e.code == 1
        else:
            raise AssertionError("should have exited")
