"""bash — the agent's hands. LLM=brain, bash=body.

One tool to replace filesystem + shell + tool-writer + browser-setup.
The agent can do ANYTHING the system user can do.

Safety: delete() requires user confirmation.
"""

from __future__ import annotations

import os
import subprocess


def run(command: str, timeout: int = 30) -> str:
    """Execute a shell command. Returns stdout, stderr, and exit code.

    This is your primary tool. Use it for: installing packages, starting
    services, checking system state, listing files, reading files (cat/type),
    writing files (echo/cat > file), creating directories (mkdir),
    moving files, running Python scripts, and anything else you need.

    Examples:
      run("pip install browser-harness")
      run("python -c 'print(1+1)'")
      run('echo "hello" > /tmp/greeting.txt')
      run("ls -la ~/.therain2020-agent/.generated/")
    """
    try:
        p = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = p.stdout.strip()
        err = p.stderr.strip()
        parts = []
        if out:
            parts.append(out[:5000])
        if err:
            parts.append(f"[stderr]\n{err[:2000]}")
        if p.returncode != 0:
            parts.append(f"[exit: {p.returncode}]")
        return "\n".join(parts) if parts else f"(exit {p.returncode})"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


def read(path: str) -> str:
    """Read a file. Convenience wrapper — same as run('cat path') but safer."""
    try:
        expanded = os.path.expanduser(path)
        return open(expanded, encoding="utf-8").read()
    except FileNotFoundError:
        return f"File not found: {path}"
    except UnicodeDecodeError:
        return f"Binary file (cannot decode as text): {path}"
    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"ERROR reading {path}: {e}"


def write(path: str, content: str) -> str:
    """Write content to a file. Creates parent directories automatically."""
    try:
        expanded = os.path.expanduser(path)
        os.makedirs(os.path.dirname(expanded), exist_ok=True)
        with open(expanded, "w", encoding="utf-8") as f:
            f.write(content)
        size = len(content)
        return f"Wrote {size} bytes to {path}"
    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"ERROR writing {path}: {e}"


def delete(path: str, confirmed: bool = False) -> str:
    """Delete a file or directory. Requires user confirmation.

    The first call will fail with "requires confirmation".
    Show the user what you want to delete and why, then they will confirm.
    On the second call, pass confirmed=True.
    """
    if not confirmed:
        return (
            f"CONFIRM DELETE: {path}\n"
            f"To proceed, call again with confirmed=True.\n"
            f"Explain to the user what you are deleting and why."
        )
    try:
        import shutil
        expanded = os.path.expanduser(path)
        if os.path.isdir(expanded):
            shutil.rmtree(expanded)
        else:
            os.remove(expanded)
        return f"Deleted: {path}"
    except FileNotFoundError:
        return f"File not found: {path}"
    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"ERROR deleting {path}: {e}"
