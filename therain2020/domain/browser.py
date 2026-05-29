"""Browser — direct CDP WebSocket to Chrome. No daemon, no deps.

Chrome must be running with --remote-debugging-port=9222.
_ensure_ready() auto-finds and launches Chrome if needed.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket  # websocket-client (sync)

_PORT = 9222
_WS: websocket.WebSocket | None = None
_SID = ""  # CDP session ID
_MSG_ID = 0


# -- internal: CDP -------------------------------------------------------

def _next_id():
    global _MSG_ID
    _MSG_ID += 1
    return _MSG_ID


def _send(method: str, params: dict | None = None) -> dict:
    msg = {"id": _next_id(), "method": method, "params": params or {}}
    if _SID:
        msg["sessionId"] = _SID
    _WS.send(json.dumps(msg))
    raw = _WS.recv()
    data = json.loads(raw)
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data.get("result", {})


# -- internal: connection ------------------------------------------------

def _find_chrome() -> str | None:
    if sys.platform == "win32":
        for pf in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ):
            for sub in (
                r"Google\Chrome\Application\chrome.exe",
                r"Microsoft\Edge\Application\msedge.exe",
            ):
                p = os.path.join(pf, sub)
                if os.path.isfile(p):
                    return p
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for sub in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",):
                    try:
                        with winreg.OpenKey(root, sub) as k:
                            val = winreg.QueryValue(k, "")
                            if val and os.path.isfile(val):
                                return val
                    except OSError:
                        pass
        except Exception:
            pass
    else:
        for n in ("google-chrome-stable", "google-chrome", "chromium-browser"):
            f = shutil.which(n)
            if f:
                return f
    return None


def _chrome_listening() -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/json/version", timeout=1).close()
        return True
    except Exception:
        return False


def _ensure_ready():
    global _WS, _SID, _MSG_ID
    if _WS and _WS.connected:
        return

    # Find or launch Chrome
    if not _chrome_listening():
        chrome = _find_chrome()
        if not chrome:
            raise RuntimeError("Chrome not found. Install Chrome or set BH_CHROME_PATH.")
        profile = os.path.join(os.path.expanduser("~"),
                               ".therain2020-agent", "chrome-profile")
        os.makedirs(profile, exist_ok=True)
        subprocess.Popen(
            f'start "" "{chrome}" --remote-debugging-port={_PORT} '
            f'--remote-allow-origins=* --user-data-dir="{profile}"',
            shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(20):
            time.sleep(0.5)
            if _chrome_listening():
                break
        else:
            raise RuntimeError(
                f'Chrome did not start. HEAL: bash__run(\'start "" "{chrome}" '
                f'--remote-debugging-port={_PORT} --remote-allow-origins=* '
                f'--user-data-dir="{profile}"' + "')"
            )

    # Connect WebSocket directly to Chrome CDP
    try:
        resp = json.loads(
            urllib.request.urlopen(
                f"http://127.0.0.1:{_PORT}/json/version", timeout=5,
            ).read()
        )
        ws_url = resp["webSocketDebuggerUrl"]
    except Exception as e:
        raise RuntimeError(f"Cannot connect to Chrome CDP: {e}")

    _WS = websocket.create_connection(ws_url, timeout=10)
    _MSG_ID = 0

    # Find or create a page target
    targets = _send("Target.getTargets")["targetInfos"]
    pages = [
        t for t in targets
        if t["type"] == "page"
        and not t.get("url", "").startswith(("chrome://", "devtools://"))
    ]
    if pages:
        tid = pages[0]["targetId"]
    else:
        tid = _send("Target.createTarget", {"url": "about:blank"})["targetId"]

    _SID = _send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
    _send("Page.enable")
    _send("Runtime.enable")


# -- public: navigation --------------------------------------------------

def new_tab(url: str = "about:blank") -> str:
    _ensure_ready()
    tid = _send("Target.createTarget", {"url": "about:blank"})["targetId"]
    global _SID
    _SID = _send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
    _send("Page.enable")
    if url != "about:blank":
        _send("Page.navigate", {"url": url})
    info = page_info()
    return f"Tab opened: {info.get('title', '')} — {info.get('url', url)}"


def goto_url(url: str) -> dict:
    _ensure_ready()
    return _send("Page.navigate", {"url": url})


def list_tabs(include_chrome: bool = True) -> list[dict]:
    _ensure_ready()
    targets = _send("Target.getTargets").get("targetInfos", [])
    prefixes = ("chrome://", "chrome-extension://", "devtools://", "about:")
    out = []
    for t in targets:
        if t.get("type") != "page":
            continue
        u = t.get("url", "")
        if not include_chrome and u.startswith(prefixes):
            continue
        out.append({"targetId": t["targetId"], "title": t.get("title", ""), "url": u})
    return out


def switch_tab(target: str | dict) -> str:
    _ensure_ready()
    tid = target if isinstance(target, str) else target["targetId"]
    _send("Target.activateTarget", {"targetId": tid})
    global _SID
    _SID = _send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
    return _SID


def close_tab(target: str | dict | None = None):
    _ensure_ready()
    if target is None:
        tabs = list_tabs(include_chrome=False)
        if not tabs:
            return
        target = tabs[0]["targetId"]
    tid = target if isinstance(target, str) else target["targetId"]
    _send("Target.closeTarget", {"targetId": tid})


# -- public: inspection --------------------------------------------------

def page_info() -> dict:
    _ensure_ready()
    expr = (
        "JSON.stringify({url:location.href,title:document.title,"
        "w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,"
        "pw:document.documentElement.scrollWidth,"
        "ph:document.documentElement.scrollHeight})"
    )
    r = _send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return json.loads(r.get("result", {}).get("value", "{}"))


def capture_screenshot(path: str | None = None, full: bool = False,
                       max_dim: int | None = 1800) -> str:
    _ensure_ready()
    r = _send("Page.captureScreenshot",
              {"format": "png", "captureBeyondViewport": full})
    data = base64.b64decode(r["data"])
    path = path or str(Path.home() / ".therain2020-agent" / "screenshot.png")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if max_dim:
        try:
            from PIL import Image
            img = Image.open(path)
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim))
                img.save(path)
        except ImportError:
            pass
    return path


# -- public: input -------------------------------------------------------

def click_at_xy(x: int, y: int, button: str = "left", clicks: int = 1):
    _ensure_ready()
    for _ in range(clicks):
        _send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": button, "clickCount": 1,
        })
        _send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": button, "clickCount": 1,
        })


def type_text(text: str):
    _ensure_ready()
    _send("Input.insertText", {"text": text})


_KEYS = {
    "Enter": (13, "Enter", "\r"), "Tab": (9, "Tab", "\t"),
    "Backspace": (8, "Backspace", ""), "Escape": (27, "Escape", ""),
    "Delete": (46, "Delete", ""), " ": (32, "Space", " "),
    "ArrowLeft": (37, "ArrowLeft", ""), "ArrowUp": (38, "ArrowUp", ""),
    "ArrowRight": (39, "ArrowRight", ""), "ArrowDown": (40, "ArrowDown", ""),
}


def press_key(key: str, modifiers: int = 0):
    _ensure_ready()
    vk, code, text = _KEYS.get(key, (
        ord(key[0]) if len(key) == 1 else 0, key,
        key if len(key) == 1 else "",
    ))
    base = {
        "key": key, "code": code, "modifiers": modifiers,
        "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
    }
    _send("Input.dispatchKeyEvent", {"type": "keyDown", **base,
          **({"text": text} if text else {})})
    if text and len(text) == 1:
        _send("Input.dispatchKeyEvent", {"type": "char", "text": text,
              **{k: v for k, v in base.items() if k != "text"}})
    _send("Input.dispatchKeyEvent", {"type": "keyUp", **base})


def scroll(x: int, y: int, dy: int = -300, dx: int = 0):
    _ensure_ready()
    _send("Input.dispatchMouseEvent", {
        "type": "mouseWheel", "x": x, "y": y,
        "deltaX": dx, "deltaY": dy,
    })


# -- public: JS ----------------------------------------------------------

def js(expression: str) -> str:
    _ensure_ready()
    r = _send("Runtime.evaluate",
              {"expression": expression, "returnByValue": True, "awaitPromise": True})
    return str(r.get("result", {}).get("value", ""))


# -- public: wait --------------------------------------------------------

def wait(seconds: float = 1.0):
    time.sleep(seconds)


def wait_for_load(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _send("Runtime.evaluate",
                      {"expression": "document.readyState", "returnByValue": True})
            if r.get("result", {}).get("value") == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def wait_for_element(selector: str, timeout: float = 10.0,
                     visible: bool = False) -> bool:
    check = (
        f"!!document.querySelector({json.dumps(selector)})"
        if not visible else
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return false;"
        f"if(typeof e.checkVisibility==='function')"
        f"return e.checkVisibility({{checkOpacity:true,checkVisibilityCSS:true}});"
        f"const s=getComputedStyle(e);"
        f"return s.display!=='none'&&s.visibility!=='hidden'}})()"
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _send("Runtime.evaluate",
                      {"expression": check, "returnByValue": True})
            if r.get("result", {}).get("value"):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False
