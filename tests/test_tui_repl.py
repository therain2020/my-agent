"""Tests for cli/tui.py and cli/repl.py — basic instantiation."""

import asyncio
import sys
from io import StringIO
from unittest.mock import patch

from therain2020.cli.repl import AgentRepl
from therain2020.run import main as run_main


def test_repl_creation():
    repl = AgentRepl()
    assert repl.turn == 0
    assert repl.conversation == []


def test_repl_handle_exit():
    repl = AgentRepl()
    repl._running = True
    asyncio.run(repl._handle_slash("/exit"))
    assert not repl._running


def test_repl_handle_help(capsys):
    repl = AgentRepl()
    asyncio.run(repl._handle_slash("/help"))
    captured = capsys.readouterr()
    assert "help" in captured.out.lower()


def test_run_cli_help_flag():
    stdout = StringIO()
    with patch.object(sys, "argv", ["therain2020", "--help"]), \
         patch("sys.stdout", stdout):
        asyncio.run(run_main())
    assert "Usage" in stdout.getvalue()


def test_run_tui_flag():
    with patch.object(sys, "argv", ["therain2020", "--tui"]), \
         patch("therain2020.cli.tui.run_tui") as mock_tui:
        asyncio.run(run_main())
    mock_tui.assert_called_once()


def test_run_repl_flag():
    with patch.object(sys, "argv", ["therain2020", "--repl"]), \
         patch("therain2020.cli.repl.run_repl") as mock_repl:
        asyncio.run(run_main())
    mock_repl.assert_called_once()
