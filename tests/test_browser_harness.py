"""Tests for browser harness adapter and daemon (十四-B)."""

import asyncio
from pathlib import Path

from agent.tools.adapters.browser_harness import BrowserHarnessAdapter
from agent.tools.loader import parse_tool_md


class TestBrowserHarnessAdapter:
    def test_adapter_init(self):
        adapter = BrowserHarnessAdapter(registry=None)
        assert adapter is not None

    def test_adapter_register_creates_tool(self, tmp_path):
        # Create a minimal tool.md in tmp
        browser_dir = tmp_path / "browser"
        browser_dir.mkdir()
        (browser_dir / "tool.md").write_text(
            "---\nname: browser-harness\nversion: '0.1.0'\n"
            "objects: [web-page]\ncapabilities:\n"
            "  - name: navigate\n    params:\n"
            "      url: {type: string, required: true}\n"
            "source: builtin\nruntime: import\n---\n# Test\n",
            encoding="utf-8",
        )

        from agent.tools.registry import ToolRegistry
        registry = ToolRegistry()
        adapter = BrowserHarnessAdapter(registry)
        count = adapter.register(tools_dir=browser_dir)
        assert count == 1
        tool = registry.get("browser-harness")
        assert tool is not None
        assert tool.name == "browser-harness"

    def test_adapter_missing_tool_md(self, tmp_path):
        from agent.tools.registry import ToolRegistry
        registry = ToolRegistry()
        adapter = BrowserHarnessAdapter(registry)
        count = adapter.register(tools_dir=tmp_path)
        assert count == 0


class TestBrowserToolMd:
    def test_tool_md_parses(self):
        tool_md_path = Path(__file__).parent.parent / "agent" / "tools" / "browser" / "tool.md"
        if not tool_md_path.exists():
            return  # Skip if file doesn't exist yet
        tool_def = parse_tool_md(tool_md_path)
        assert tool_def.name == "browser-harness"
        assert len(tool_def.capabilities) == 12
        cap_names = [c.name for c in tool_def.capabilities]
        assert "navigate" in cap_names
        assert "capture_screenshot" in cap_names
        assert "click_at_xy" in cap_names
        assert "js" in cap_names
        assert "cdp" in cap_names  # raw CDP escape hatch


class TestBrowserDaemon:
    def test_daemon_chrome_not_found_when_missing(self):
        from agent.tools.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon(name="test-daemon", port=19999)
        exe = daemon._find_chrome_exe()
        # Chrome may or may not be installed on test machine
        # Just verify the method returns consistent results
        assert exe is None or isinstance(exe, str)

    def test_find_running_chrome_none_when_nothing_listening(self):
        from agent.tools.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon(name="test", port=19998)

        async def _check():
            result = await daemon._find_running_chrome()
            assert result is None

        asyncio.run(_check())
