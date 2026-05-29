"""Shell execution — gives agent real system-level power.

Without this, self-healing is impossible. Agent can't install packages,
can't start daemons, can't run diagnostics.

Safety: non-interactive only, 30s timeout, output capped at 5000 chars.
"""

from __future__ import annotations

import subprocess


def run(command: str, timeout: int = 30) -> str:
    """Execute a shell command. Returns stdout+stderr+exit code.

    Use this for: installing packages, starting services, checking
    system state, running CLI tools.

    Do NOT use for: interactive programs (vim, top, ssh), commands
    that run forever, or anything destructive without user approval.
    """
    try:
        p = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=None,
        )
        out = p.stdout.strip()
        err = p.stderr.strip()
        parts = []
        if out:
            parts.append(out[:5000])
        if err:
            parts.append(f"[stderr]\n{err[:2000]}")
        if p.returncode != 0:
            parts.append(f"[exit code: {p.returncode}]")
        return "\n".join(parts) if parts else f"(exit {p.returncode})"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"
