"""browser-setup: Agent self-bootstraps browser-harness connection.

When browser tools fail with "daemon not running", the agent can call
this to auto-configure the connection — no manual user steps needed
for Way 2 (dedicated Chrome with --remote-debugging-port).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time


def setup(port: int = 9222) -> str:
    """Auto-configure browser-harness. Returns status string."""

    # 1. Check browser-harness installed
    bh_cmd = _find_browser_harness()
    if not bh_cmd:
        return _fail(
            "browser-harness not installed. "
            "Fix: shell__run('pip install browser-harness') then retry browser-setup__setup()"
        )

    # 2. Find Chrome
    chrome = _find_chrome()
    if not chrome:
        return _fail(
            "No Chrome/Chromium found. Install Chrome or set BH_CHROME_PATH."
        )

    # 3. Launch Chrome with remote debugging
    user_data = os.environ.get(
        "BH_CHROME_USER_DATA",
        str(os.path.join(
            os.path.expanduser("~"), ".therain2020-agent", "chrome-profile"
        )),
    )
    os.makedirs(user_data, exist_ok=True)

    # Check if Chrome is already running on our port
    if _chrome_listening(port):
        return _ok(f"Chrome already listening on port {port}")

    # Launch Chrome
    try:
        subprocess.Popen(
            [chrome, f"--remote-debugging-port={port}", f"--user-data-dir={user_data}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return _fail(f"Failed to launch Chrome: {e}")

    # 4. Wait for Chrome to be ready
    for _ in range(30):
        if _chrome_listening(port):
            break
        time.sleep(1)
    else:
        return _fail("Chrome launched but DevTools not responding on port {port}")

    # 5. Set env for browser-harness
    os.environ["BU_CDP_URL"] = f"http://127.0.0.1:{port}"

    # 6. Start browser-harness daemon
    try:
        subprocess.Popen(
            [sys.executable, "-m", "browser_harness.daemon"],
            env={**os.environ, "BU_CDP_URL": f"http://127.0.0.1:{port}"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return _fail(f"Failed to start browser-harness daemon: {e}")

    # 7. Wait for daemon
    for _ in range(10):
        if _daemon_alive():
            return _ok(
                f"Browser connected on port {port}. "
                f"Chrome user data: {user_data}"
            )
        time.sleep(1)

    return _fail("Daemon didn't start in time. Check logs.")


def status() -> str:
    """Report current browser connection status."""
    parts = []
    if _find_browser_harness():
        parts.append("browser-harness: installed")
    else:
        parts.append("browser-harness: NOT installed")
        return "; ".join(parts)

    if _chrome_running():
        parts.append("Chrome: running")
    else:
        parts.append("Chrome: NOT running")

    if _daemon_alive():
        parts.append("daemon: alive")
    else:
        parts.append("daemon: NOT running")

    return "; ".join(parts)


def _find_browser_harness():
    """Find browser-harness CLI. Tries shutil.which, pip show, and common paths."""
    if found := shutil.which("browser-harness"):
        return found
    # pip install may put scripts in a location not yet in PATH
    if found := shutil.which("browser-harness.exe"):
        return found
    # Check via pip
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "browser-harness"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("Location:"):
                    loc = line.split(":", 1)[1].strip()
                    # Look for the script in the scripts directory
                    scripts = os.path.join(loc, "..", "..", "Scripts",
                                           "browser-harness.exe" if sys.platform == "win32" else "browser-harness")
                    scripts = os.path.normpath(scripts)
                    if os.path.isfile(scripts):
                        return scripts
                    # Also check bin/
                    scripts = os.path.join(loc, "..", "..", "bin", "browser-harness")
                    scripts = os.path.normpath(scripts)
                    if os.path.isfile(scripts):
                        return scripts
    except Exception:
        pass
    return None


# -- helpers -------------------------------------------------------------

def _find_chrome():
    """Cross-platform Chrome discovery — exhaustive search."""
    if path := os.environ.get("BH_CHROME_PATH"):
        if os.path.isfile(path):
            return path

    if sys.platform == "win32":
        # Exhaustive Windows search: registry + all known paths
        names = []
        # Try registry first
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for sub in (
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
                ):
                    try:
                        with winreg.OpenKey(root, sub) as k:
                            names.append(winreg.QueryValue(k, ""))
                    except OSError:
                        pass
        except Exception:
            pass
        # Known install paths
        names += [
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for n in names:
            if n and os.path.isfile(n):
                return n
        # Fallback: try PATH
        for n in ("chrome.exe", "msedge.exe", "chromium.exe"):
            found = shutil.which(n)
            if found:
                return found
    elif sys.platform == "darwin":
        names = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
        for n in names:
            if os.path.isfile(n):
                return n
    else:
        for n in ("google-chrome-stable", "google-chrome",
                  "chromium-browser", "chromium", "microsoft-edge"):
            found = shutil.which(n)
            if found:
                return found
    return None


def _chrome_running():
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(["tasklist"], text=True, timeout=5)
            return any(n in out.lower() for n in ("chrome.exe", "msedge.exe"))
        out = subprocess.check_output(["ps", "-A", "-o", "comm="], text=True, timeout=5)
        return any(n in out.lower() for n in ("chrome", "chromium", "msedge"))
    except Exception:
        return False


def _chrome_listening(port):
    import urllib.request
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=1
        ).close()
        return True
    except Exception:
        return False


def _daemon_alive():
    try:
        from .. import _ipc as ipc
        return ipc.ping("default", timeout=0.5)
    except Exception:
        return False


def _ok(msg):
    return f"OK: {msg}"


def _fail(msg):
    return f"FAILED: {msg}"
