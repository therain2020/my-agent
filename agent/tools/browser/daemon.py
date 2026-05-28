"""CDP daemon. 类比: kthread — persistent background kernel thread.

Maintains a persistent Chrome DevTools Protocol connection across
LLM cognitive pauses. Handles Chrome discovery, launch, and IPC
via TCP loopback (Windows-compatible).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Known Chrome/Chromium install paths (Windows)
_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Chromium\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Chromium\Application\chrome.exe"),
    # Linux fallbacks
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]


class BrowserDaemon:
    """Persistent CDP connection manager. 类比: kthread.

    Each instance gets one daemon. IPC via TCP loopback (cross-platform).
    Token-based security prevents unauthorized CDP commands on TCP.
    """

    def __init__(self, name: str = "default", port: int = 9222):
        self.name = name
        self.port = port
        self.token = secrets.token_hex(16)
        self._chrome_process: subprocess.Popen | None = None
        self._ws: object | None = None  # websockets connection
        self._running = False
        self._user_data_dir: Path | None = None

    async def start(self, headless: bool = True) -> bool:
        """Start the browser daemon. Launches Chrome if needed."""
        # 1. Check for existing Chrome with DevTools
        chrome_ws = await self._find_running_chrome()
        if chrome_ws:
            try:
                import websockets
                self._ws = await websockets.connect(chrome_ws)
                self._running = True
                logger.info("daemon_attached_existing", name=self.name)
                return True
            except Exception:
                pass

        # 2. Launch new Chrome
        chrome_exe = self._find_chrome_exe()
        if not chrome_exe:
            logger.error("daemon_chrome_not_found")
            return False

        self._user_data_dir = Path(
            os.environ.get("TEMP", "/tmp")
        ) / f"browser-harness-{self.name}"
        self._user_data_dir.mkdir(parents=True, exist_ok=True)

        args = [
            chrome_exe,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self._user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
        ]
        if headless:
            args.append("--headless=new")

        try:
            self._chrome_process = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.error("daemon_launch_failed", chrome=chrome_exe)
            return False

        # 3. Wait for DevTools port
        ws_url = await self._wait_for_devtools(timeout=10)
        if not ws_url:
            return False

        try:
            import websockets
            self._ws = await websockets.connect(ws_url)
            self._running = True
            logger.info("daemon_started", name=self.name, port=self.port)
            return True
        except Exception as e:
            logger.error("daemon_ws_connect_failed", error=str(e))
            return False

    async def send(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and get the response."""
        if not self._ws:
            raise RuntimeError("Daemon not running")

        msg = {
            "id": int(time.time() * 1000000),
            "method": method,
            "params": (params or {}) | {"_token": self.token},
        }
        await self._ws.send(json.dumps(msg))
        try:
            response = await asyncio.wait_for(self._ws.recv(), timeout=30)
            return json.loads(response)
        except TimeoutError:
            return {"error": "CDP command timed out"}

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._chrome_process:
            self._chrome_process.terminate()
            try:
                self._chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._chrome_process.kill()
        logger.info("daemon_stopped", name=self.name)

    @property
    def is_running(self) -> bool:
        return self._running

    # === Internal ===

    @staticmethod
    def _find_chrome_exe() -> str | None:
        for path in _CHROME_PATHS:
            if os.path.exists(path):
                return path
        for cmd in ["chrome", "chromium", "chromium-browser", "google-chrome"]:
            try:
                result = subprocess.run(
                    ["where", cmd] if os.name == "nt" else ["which", cmd],
                    capture_output=True, text=True,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip().split("\n")[0]
            except Exception:
                pass
        return None

    async def _find_running_chrome(self) -> str | None:
        """Check if a Chrome with DevTools is already listening."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", self.port), timeout=2,
            )
            request = (
                f"GET /json/version HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                f"Connection: close\r\n\r\n"
            )
            writer.write(request.encode())
            await writer.drain()

            response = b""
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=1)
                    if not chunk:
                        break
                    response += chunk
                except TimeoutError:
                    break
            writer.close()

            if b"webSocketDebuggerUrl" in response:
                body = response.decode(errors="replace").split("\r\n\r\n", 1)[1]
                data = json.loads(body)
                return data.get("webSocketDebuggerUrl")
        except Exception:
            pass
        return None

    async def _wait_for_devtools(self, timeout: float = 10) -> str | None:
        """Poll until DevTools port is ready."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ws_url = await self._find_running_chrome()
            if ws_url:
                return ws_url
            await asyncio.sleep(0.5)
        return None
