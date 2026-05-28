"""Browser interaction helpers. Agent-editable surface.

Design decisions (from Browser Harness):
- Coordinate click default (Input.dispatchMouseEvent at compositor level)
- Screenshot-first: capture -> read pixels -> click -> verify
- Direct CDP, no framework abstraction
- Core helpers stay short
- Suppress "locate first, then click" reflex
"""

from __future__ import annotations

import asyncio
import time
from typing import Any


class BrowserHelpers:
    """Browser interaction helpers. 类比: VFS file_operations.

    All helpers pre-imported into the agent's execution namespace.
    """

    def __init__(self, daemon: Any):
        self.daemon = daemon

    # === Navigation ===

    async def navigate(self, url: str) -> dict:
        return await self.daemon.send("Page.navigate", {"url": url})

    async def reload(self) -> dict:
        return await self.daemon.send("Page.reload")

    async def current_url(self) -> str:
        result = await self.js("window.location.href")
        return str(result.get("result", {}).get("value", ""))

    # === Screenshot (primary interaction pattern) ===

    async def capture_screenshot(self) -> str:
        """Capture screenshot. Returns base64-encoded PNG."""
        result = await self.daemon.send("Page.captureScreenshot", {
            "format": "png",
            "fromSurface": True,
        })
        return str(result.get("result", {}).get("data", ""))

    # === Coordinate click (DEFAULT interaction pattern) ===

    async def click_at_xy(self, x: float, y: float) -> dict:
        """Click at pixel coordinates. Compositor-level — bypasses iframe/shadow DOM."""
        await self.daemon.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        return await self.daemon.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })

    async def double_click_at_xy(self, x: float, y: float) -> dict:
        await self.daemon.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 2,
        })
        return await self.daemon.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 2,
        })

    # === Keyboard ===

    async def type_text(self, text: str) -> dict:
        return await self.daemon.send("Input.insertText", {"text": text})

    async def press_key(self, key: str) -> dict:
        return await self.daemon.send("Input.dispatchKeyEvent", {
            "type": "keyDown", "key": key,
        })

    # === DOM / JavaScript (fallback for structured data) ===

    async def js(self, expression: str) -> dict:
        """Execute JavaScript. Auto-wrapped in IIFE."""
        return await self.daemon.send("Runtime.evaluate", {
            "expression": f"(function() {{ return {expression}; }})()",
            "returnByValue": True,
            "awaitPromise": True,
        })

    async def get_page_text(self) -> str:
        result = await self.js("document.body.innerText")
        return str(result.get("result", {}).get("value", ""))

    async def get_element_info(self, selector: str) -> dict | None:
        """Get bounding box and attributes (DOM fallback for structured data)."""
        result = await self.js(f"""
            (function() {{
                const el = document.querySelector('{selector}');
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {{
                    x: rect.x, y: rect.y,
                    width: rect.width, height: rect.height,
                    visible: rect.width > 0 && rect.height > 0,
                    text: el.textContent?.substring(0, 200),
                    tag: el.tagName,
                }};
            }})()
        """)
        return result.get("result", {}).get("value")

    # === Input (framework-aware) ===

    async def fill_input(self, selector: str, value: str) -> dict:
        """Fill an input field. React/Vue/Ember framework-aware."""
        await self.js(f"""
            (function() {{
                const el = document.querySelector('{selector}');
                if (!el) return;
                el.focus();
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(el, '{value}');
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }})()
        """)
        return await self.type_text(value)

    # === CDP raw channel (escape hatch) ===

    async def cdp(self, method: str, params: dict | None = None) -> dict:
        """Raw CDP command — escape hatch for anything not in helpers."""
        return await self.daemon.send(method, params)

    # === Page info ===

    async def page_info(self) -> dict:
        title_r = await self.js("document.title")
        url = await self.current_url()
        return {
            "title": title_r.get("result", {}).get("value", ""),
            "url": url,
        }

    async def wait_for_network_idle(self, timeout: float = 5.0) -> bool:
        """Wait for network activity to settle."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
        return True
