"""IPC primitives for browser-harness daemon communication.

Thin adapter that talks to the browser-harness daemon over its
JSON-line protocol (Unix socket on POSIX, TCP loopback on Windows).

Reference: browser-harness src/browser_harness/_ipc.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
_RUNTIME = Path(os.environ.get("BH_RUNTIME_DIR", os.environ.get("BH_TMP_DIR", "/tmp" if not IS_WINDOWS else "")))


def _sock_path(name: str) -> Path:
    stem = f"bu-{name}"
    if IS_WINDOWS:
        return _RUNTIME / f"{stem}.port"
    return _RUNTIME / f"{stem}.sock"


def _read_port_file(name: str) -> tuple[int | None, str | None]:
    path = _sock_path(name)
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text())
        return int(data["port"]), data["token"]
    except (FileNotFoundError, ValueError, KeyError, TypeError, OSError):
        return None, None


def connect(name: str = "default", timeout: float = 5.0) -> tuple[socket.socket, str | None]:
    """Connect to browser-harness daemon. Returns (socket, token)."""
    if not IS_WINDOWS:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(str(_sock_path(name)))
        return s, None
    port, token = _read_port_file(name)
    if port is None:
        raise FileNotFoundError(f"browser-harness daemon not found: {_sock_path(name)}")
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.settimeout(timeout)
    return s, token


def request(sock: socket.socket, token: str | None, req: dict) -> dict:
    """Send a request and receive the response over a browser-harness IPC socket."""
    if token:
        req = {**req, "token": token}
    sock.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = sock.recv(1 << 16)
        if not chunk:
            break
        data += chunk
    return json.loads(data or "{}")


def ping(name: str = "default", timeout: float = 1.0) -> bool:
    """Check if a browser-harness daemon is alive."""
    try:
        c, token = connect(name, timeout=timeout)
        resp = request(c, token, {"meta": "ping"})
        c.close()
        return isinstance(resp, dict) and resp.get("pong") is True
    except (FileNotFoundError, ConnectionRefusedError, TimeoutError, OSError, ValueError):
        return False


def cdp(method: str, name: str = "default", session_id: str | None = None, **params) -> dict:
    """Send a raw CDP command through the browser-harness daemon."""
    c, token = connect(name)
    try:
        resp = request(c, token, {"method": method, "params": params, "session_id": session_id})
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp.get("result", {})
    finally:
        c.close()
