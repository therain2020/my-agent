"""Browser domain tool — real CDP via browser-harness IPC.

Requires browser-harness daemon running (connected to user's Chrome).
Install: pip install browser-harness
Connect: open chrome://inspect/#remote-debugging, tick checkbox, click Allow.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from .. import _ipc as ipc

_DAEMON = "default"


def _cdp(method, **params):
    """Send a CDP command through the browser-harness daemon."""
    try:
        return ipc.cdp(method, name=_DAEMON, **params)
    except (FileNotFoundError, ConnectionRefusedError, TimeoutError, OSError) as e:
        raise RuntimeError(
            "No browser connected. Make sure Chrome is running with remote "
            "debugging enabled (chrome://inspect/#remote-debugging). "
            f"IPC error: {e}"
        )


def _check_daemon():
    if not ipc.ping(_DAEMON, timeout=0.5):
        raise RuntimeError(
            "browser-harness daemon not running. "
            "Start it with: browser-harness <<'PY'\nprint(page_info())\nPY"
        )


# -- navigation ----------------------------------------------------------

def new_tab(url: str = "about:blank") -> str:
    _check_daemon()
    tid = _cdp("Target.createTarget", url="about:blank")["targetId"]
    sid = _cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    _cdp("Page.enable", session_id=sid)
    if url != "about:blank":
        _cdp("Page.navigate", url=url, session_id=sid)
    # Notify daemon of new session
    try:
        c, token = ipc.connect(_DAEMON)
        ipc.request(c, token, {"meta": "set_session", "session_id": sid, "target_id": tid})
        c.close()
    except Exception:
        pass
    return tid


def goto_url(url: str) -> dict:
    return _cdp("Page.navigate", url=url)


def list_tabs(include_chrome: bool = True) -> list[dict]:
    targets = _cdp("Target.getTargets").get("targetInfos", [])
    chrome_prefixes = ("chrome://", "chrome-extension://", "devtools://", "about:")
    out = []
    for t in targets:
        if t.get("type") != "page":
            continue
        u = t.get("url", "")
        if not include_chrome and u.startswith(chrome_prefixes):
            continue
        out.append({
            "targetId": t["targetId"],
            "title": t.get("title", ""),
            "url": u,
        })
    return out


def switch_tab(target: str | dict) -> str:
    tid = target if isinstance(target, str) else target["targetId"]
    _cdp("Target.activateTarget", targetId=tid)
    return _cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]


def close_tab(target: str | dict | None = None):
    if target is None:
        tabs = list_tabs(include_chrome=False)
        if not tabs:
            return
        target = tabs[0]["targetId"]
    tid = target if isinstance(target, str) else target["targetId"]
    _cdp("Target.closeTarget", targetId=tid)


# -- visual / inspection -------------------------------------------------

def page_info() -> dict:
    expression = (
        "JSON.stringify({url:location.href,title:document.title,"
        "w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,"
        "pw:document.documentElement.scrollWidth,"
        "ph:document.documentElement.scrollHeight})"
    )
    result = _cdp("Runtime.evaluate", expression=expression, returnByValue=True)
    return json.loads(result.get("result", {}).get("value", "{}"))


def capture_screenshot(path: str | None = None, full: bool = False,
                       max_dim: int | None = 1800) -> str:
    r = _cdp("Page.captureScreenshot", format="png", captureBeyondViewport=full)
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


# -- input ---------------------------------------------------------------

def click_at_xy(x: int, y: int, button: str = "left", clicks: int = 1):
    _cdp("Input.dispatchMouseEvent", type="mousePressed",
         x=x, y=y, button=button, clickCount=clicks)
    _cdp("Input.dispatchMouseEvent", type="mouseReleased",
         x=x, y=y, button=button, clickCount=clicks)


def type_text(text: str):
    _cdp("Input.insertText", text=text)


_PRESS_KEYS = {
    "Enter": (13, "Enter", "\r"), "Tab": (9, "Tab", "\t"),
    "Backspace": (8, "Backspace", ""), "Escape": (27, "Escape", ""),
    "Delete": (46, "Delete", ""), " ": (32, "Space", " "),
    "ArrowLeft": (37, "ArrowLeft", ""), "ArrowUp": (38, "ArrowUp", ""),
    "ArrowRight": (39, "ArrowRight", ""), "ArrowDown": (40, "ArrowDown", ""),
}


def press_key(key: str, modifiers: int = 0):
    vk, code, text = _PRESS_KEYS.get(key, (
        ord(key[0]) if len(key) == 1 else 0, key,
        key if len(key) == 1 else "",
    ))
    base = {"key": key, "code": code, "modifiers": modifiers,
            "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
    _cdp("Input.dispatchKeyEvent", type="keyDown", **base,
         **({"text": text} if text else {}))
    if text and len(text) == 1:
        _cdp("Input.dispatchKeyEvent", type="char", text=text,
             **{k: v for k, v in base.items() if k != "text"})
    _cdp("Input.dispatchKeyEvent", type="keyUp", **base)


def scroll(x: int, y: int, dy: int = -300, dx: int = 0):
    _cdp("Input.dispatchMouseEvent", type="mouseWheel",
         x=x, y=y, deltaX=dx, deltaY=dy)


# -- JS execution --------------------------------------------------------

def js(expression: str) -> str:
    result = _cdp("Runtime.evaluate", expression=expression, returnByValue=True,
                  awaitPromise=True)
    return str(result.get("result", {}).get("value", ""))


# -- waiting -------------------------------------------------------------

def wait(seconds: float = 1.0):
    time.sleep(seconds)


def wait_for_load(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ready = _cdp("Runtime.evaluate", expression="document.readyState",
                         returnByValue=True)
            if ready.get("result", {}).get("value") == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def wait_for_element(selector: str, timeout: float = 10.0,
                     visible: bool = False) -> bool:
    if visible:
        check = (
            f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
            f"if(!e)return false;"
            f"if(typeof e.checkVisibility==='function')"
            f"return e.checkVisibility({{checkOpacity:true,checkVisibilityCSS:true}});"
            f"const s=getComputedStyle(e);"
            f"return s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'}})()"
        )
    else:
        check = f"!!document.querySelector({json.dumps(selector)})"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _cdp("Runtime.evaluate", expression=check, returnByValue=True)
            if r.get("result", {}).get("value"):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False
