"""Search engine abstraction. Python default, ripgrep optional.

Automatically detects and uses rg if available.
User can override via config: search.engine = python | ripgrep
"""

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import structlog

logger = structlog.get_logger()


@dataclass
class SearchMatch:
    file: str
    line: int          # 1-based
    content: str
    keyword: str = ""
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)


class SearchEngine(Protocol):
    """Search engine interface."""

    @property
    def name(self) -> str:
        """Engine name: 'python' | 'ripgrep'"""
        ...

    def search(
        self,
        path: str | Path,
        pattern: str,
        *,
        glob: str | None = None,
        ignore_case: bool = True,
        max_results: int = 50,
        context_lines: int = 0,
    ) -> list[SearchMatch]:
        ...

    def count(self, path: str | Path, pattern: str) -> int:
        ...


class PythonSearchEngine:
    """Zero-dependency Python search. Always available."""

    name = "python"

    def search(self, path, pattern, *, glob=None, ignore_case=True,
               max_results=50, context_lines=0):
        results = []
        search_path = Path(path)
        pattern_lower = pattern.lower() if ignore_case else pattern

        if search_path.is_file():
            files = [search_path]
        else:
            files = list(search_path.rglob(glob or "*"))
            files = [f for f in files if f.is_file()]

        for file_path in files:
            if len(results) >= max_results:
                break
            try:
                lines = file_path.read_text(encoding="utf-8").split("\n")
            except (UnicodeDecodeError, OSError):
                continue

            for i, line in enumerate(lines):
                target = line.lower() if ignore_case else line
                if pattern_lower in target:
                    results.append(SearchMatch(
                        file=str(file_path),
                        line=i + 1,
                        content=line.strip(),
                        keyword=pattern,
                        context_before=(
                            lines[max(0, i - context_lines):i]
                            if context_lines else []
                        ),
                        context_after=(
                            lines[i + 1:i + 1 + context_lines]
                            if context_lines else []
                        ),
                    ))
                    if len(results) >= max_results:
                        break

        return results

    def count(self, path, pattern):
        return len(self.search(path, pattern, max_results=99999))


class RipgrepSearchEngine:
    """ripgrep-powered search. 5-10x faster, regex support."""

    name = "ripgrep"

    def __init__(self, rg_path: str = "rg"):
        self._rg = rg_path

    def search(self, path, pattern, *, glob=None, ignore_case=True,
               max_results=50, context_lines=0):
        args = [
            self._rg, "--no-heading", "-n",
            "--max-count", str(max_results),
        ]
        if ignore_case:
            args.append("-i")
        if context_lines:
            args.extend(["-C", str(context_lines)])
        if glob:
            args.extend(["--glob", glob])

        args.extend([pattern, str(path)])

        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=15,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        return self._parse(result.stdout, pattern, context_lines)

    def _parse(self, stdout, pattern, context_lines):
        results = []
        for line in stdout.strip().split("\n"):
            if not line or line.startswith("--"):
                continue
            parts = line.split(":", 2)
            if len(parts) >= 3:
                results.append(SearchMatch(
                    file=parts[0], line=int(parts[1]),
                    content=parts[2].strip(), keyword=pattern,
                ))
        return results

    def count(self, path, pattern):
        try:
            result = subprocess.run(
                [self._rg, "--count", pattern, str(path)],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return 0
        total = 0
        for line in result.stdout.strip().split("\n"):
            if ":" in line:
                try:
                    total += int(line.split(":")[-1])
                except ValueError:
                    pass
        return total


class SearchEngineRegistry:
    """Manage available engines, auto-select best."""

    def __init__(self):
        self._engines: dict[str, SearchEngine] = {}
        self._default: str = ""

    def register(self, engine: SearchEngine):
        self._engines[engine.name] = engine

    def detect_best(self) -> str:
        if shutil.which("rg"):
            return "ripgrep"
        return "python"

    def get(self, name: str = "") -> SearchEngine:
        engine_name = name or self._default or self.detect_best()
        if engine_name not in self._engines:
            raise ValueError(
                f"Unknown search engine: {engine_name}. "
                f"Available: {list(self._engines)}"
            )
        return self._engines[engine_name]

    def set_default(self, name: str):
        if name not in self._engines:
            raise ValueError(f"Unknown engine: {name}")
        self._default = name
        logger.info("search_engine_set", engine=name)

    @property
    def available_engines(self) -> list[str]:
        return list(self._engines.keys())

    @property
    def current_engine(self) -> str:
        return self._default or self.detect_best()


_default_registry = SearchEngineRegistry()
_default_registry.register(PythonSearchEngine())
if shutil.which("rg"):
    _default_registry.register(RipgrepSearchEngine())


def get_search_engine(name: str = "") -> SearchEngine:
    """Get the default search engine. Install once, use everywhere."""
    return _default_registry.get(name)
