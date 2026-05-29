"""Three mechanisms engine: self-healing + self-evolution + memory.

heal.json persists fix recipes, known paths, and platform info.
Error enrichment injects HEAL commands directly into tool error messages.
Semantic matching handles error paraphrases.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HEAL_PATH = Path.home() / ".therain2020-agent" / "heal.json"

# -- platform -----------------------------------------------------------

@dataclass
class Platform:
    os: str = ""
    shell: str = "bash -c"
    which: str = "which"
    list_dir: str = "ls"
    path_sep: str = "/"
    null_device: str = "/dev/null"
    program_files: list[str] = field(default_factory=list)

    @classmethod
    def detect(cls) -> Platform:
        p = Platform()
        if sys.platform == "win32":
            p.os = "windows"
            p.shell = "cmd /c"
            p.which = "where"
            p.list_dir = "dir"
            p.path_sep = "\\"
            p.null_device = "nul"
            p.program_files = [
                os.environ.get("ProgramFiles", r"C:\Program Files"),
                os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                os.path.expandvars(r"%LOCALAPPDATA%"),
            ]
        elif sys.platform == "darwin":
            p.os = "macos"
        else:
            p.os = "linux"
        return p

    @property
    def tips(self) -> str:
        if self.os == "windows":
            return (
                f"Use '{self.which}' not 'which'. "
                f"Use '{self.list_dir}' not 'ls'. "
                "Use 'start' to launch programs. "
                "Shell is 'cmd /c'."
            )
        return ""


# -- semantic error matching --------------------------------------------

_ERROR_SYNONYMS = {
    "daemon not running": [
        "connection refused", "cannot connect", "websocket",
        "not alive", "no daemon", "daemon is dead",
        "browser-harness not installed",
    ],
    "not found": [
        "not installed", "no such file", "cannot find",
        "not recognized", "找不到", "is not recognized",
    ],
    "permission denied": [
        "access denied", "not permitted", "eacces",
        "permissionerror",
    ],
    "timeout": [
        "timed out", "timeout", "too slow", "deadline exceeded",
    ],
}

def _normalize_error(text: str) -> str:
    lower = text.lower()
    for canonical, synonyms in _ERROR_SYNONYMS.items():
        if any(s.lower() in lower for s in [canonical] + synonyms):
            return canonical
    return text[:80]

def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords for fuzzy matching."""
    words = text.lower().split()
    stop = {"the", "a", "an", "is", "was", "to", "in", "of", "for", "at", "on"}
    return [w for w in words if len(w) > 3 and w not in stop][:5]


# -- HealingDB ----------------------------------------------------------

@dataclass
class FixEntry:
    command: str
    tool: str = ""
    success: int = 0
    fail: int = 0
    last_used: str = ""
    first_seen: str = ""

    @property
    def confidence(self) -> float:
        total = self.success + self.fail
        return self.success / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "command": self.command, "tool": self.tool,
            "success": self.success, "fail": self.fail,
            "last_used": self.last_used, "first_seen": self.first_seen,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FixEntry:
        return cls(**{k: d.get(k, "" if k in ("command", "tool", "last_used", "first_seen") else 0)
                      for k in ("command", "tool", "success", "fail", "last_used", "first_seen")})


class HealingDB:
    def __init__(self):
        self.platform = Platform.detect()
        self.paths: dict[str, str] = {}
        self.fixes: dict[str, FixEntry] = {}
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            if HEAL_PATH.exists():
                data = json.loads(HEAL_PATH.read_text(encoding="utf-8"))
                self.paths = data.get("paths", {})
                for k, v in data.get("fixes", {}).items():
                    self.fixes[k] = FixEntry.from_dict(v)
        except Exception:
            pass

    def save(self):
        try:
            HEAL_PATH.parent.mkdir(parents=True, exist_ok=True)
            HEAL_PATH.write_text(json.dumps({
                "version": 2,
                "paths": self.paths,
                "fixes": {k: v.to_dict() for k, v in self.fixes.items()},
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # -- paths --

    def remember_path(self, name: str, value: str):
        if value and os.path.exists(value):
            self.paths[name] = value
            self.save()

    def get_path(self, name: str) -> str | None:
        self.load()
        return self.paths.get(name)

    # -- fixes --

    def record(self, error_key: str, command: str, tool: str = "",
               success: bool = True):
        self.load()
        key = _normalize_error(error_key)
        if key not in self.fixes:
            self.fixes[key] = FixEntry(
                command=command, tool=tool,
                first_seen=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
        entry = self.fixes[key]
        entry.command = command  # update with latest command
        entry.tool = tool
        if success:
            entry.success += 1
        else:
            entry.fail += 1
        entry.last_used = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.save()

    def lookup(self, error_text: str, tool: str = "") -> FixEntry | None:
        self.load()
        # 1. Normalized exact match
        key = _normalize_error(error_text)
        if key in self.fixes and self.fixes[key].confidence > 0.3:
            return self.fixes[key]
        # 2. Keyword match
        for kw in _extract_keywords(error_text):
            if kw in self.fixes and self.fixes[kw].confidence > 0.5:
                return self.fixes[kw]
        # 3. Substring match
        lower = error_text.lower()
        for k, v in self.fixes.items():
            if k.lower() in lower or any(
                w in lower for w in k.lower().split()
            ):
                if v.confidence > 0.5:
                    return v
        return None

    def enrich_error(self, error_text: str, tool: str = "") -> str:
        """Append HEAL command to error message if fix exists."""
        fix = self.lookup(error_text, tool)
        if fix and fix.confidence > 0.3:
            confidence = f"{fix.confidence:.0%}"
            total = fix.success + fix.fail
            star = " ⭐" if fix.confidence > 0.9 else ""
            return (
                f"{error_text}\n\n"
                f"  HEAL{star} ({fix.success}/{total} {confidence}): {fix.command}"
            )

        # Platform tips
        if any(kw in error_text.lower() for kw in (
            "not recognized", "不是内部", "找不到", "which:",
        )):
            return f"{error_text}\n\n  TIP: {self.platform.tips}"

        return error_text

    # -- context for system prompt --

    def context(self) -> str:
        self.load()
        parts = [f"Environment: {self.platform.os} · {self.platform.tips}"]

        if self.paths:
            paths_str = "\n".join(
                f"  {name}: {path}" for name, path in self.paths.items()
            )
            parts.append(f"Known paths:\n{paths_str}")

        confident = [
            (k, v) for k, v in self.fixes.items()
            if v.confidence > 0.7 and v.success >= 3
        ]
        if confident:
            fixes_str = "\n".join(
                f"  {k} → {v.command}" for k, v in confident[:5]
            )
            parts.append(f"Known fixes:\n{fixes_str}")

        return "\n\n".join(parts)


# -- global singleton --

_healing: HealingDB | None = None

def get() -> HealingDB:
    global _healing
    if _healing is None:
        _healing = HealingDB()
        _healing.load()
    return _healing

def save():
    if _healing:
        _healing.save()
