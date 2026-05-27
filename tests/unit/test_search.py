"""Tests for search engine."""

import tempfile
from pathlib import Path

from agent.search import (
    PythonSearchEngine,
    RipgrepSearchEngine,
    SearchEngineRegistry,
    get_search_engine,
)


class TestPythonSearchEngine:
    def test_search_finds_content(self):
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "test.md").write_text("Hello pytest\nGoodbye unittest", encoding="utf-8")
            engine = PythonSearchEngine()
            results = engine.search(d, "pytest")
            assert len(results) == 1
            assert "pytest" in results[0].content
            assert results[0].line == 1
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_search_case_insensitive(self):
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "readme.md").write_text("PYTEST is great", encoding="utf-8")
            engine = PythonSearchEngine()
            results = engine.search(d, "pytest", ignore_case=True)
            assert len(results) == 1
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_search_glob_filter(self):
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "readme.md").write_text("pytest here", encoding="utf-8")
            (Path(d) / "notes.txt").write_text("pytest there", encoding="utf-8")
            engine = PythonSearchEngine()
            results = engine.search(d, "pytest", glob="*.md")
            assert len(results) == 1
            assert results[0].file.endswith(".md")
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_search_no_match(self):
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "test.md").write_text("nothing relevant", encoding="utf-8")
            engine = PythonSearchEngine()
            results = engine.search(d, "pytest")
            assert results == []
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_count(self):
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "a.md").write_text("pytest\ntest\npytest", encoding="utf-8")
            engine = PythonSearchEngine()
            assert engine.count(d, "pytest") == 2
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_context_lines(self):
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "log.txt").write_text(
                "line before\nERROR: something broke\nline after", encoding="utf-8"
            )
            engine = PythonSearchEngine()
            results = engine.search(d, "ERROR", context_lines=1)
            assert len(results) == 1
            assert "line before" in results[0].context_before[0]
            assert "line after" in results[0].context_after[0]
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class TestSearchEngineRegistry:
    def test_auto_detect_python(self):
        reg = SearchEngineRegistry()
        reg.register(PythonSearchEngine())
        engine = reg.get()
        assert engine.name == "python"

    def test_prefer_rg_when_available(self):
        import shutil
        reg = SearchEngineRegistry()
        reg.register(PythonSearchEngine())
        if shutil.which("rg"):
            reg.register(RipgrepSearchEngine())
            # ripgrep available → auto-select
            assert reg.detect_best() == "ripgrep"
        else:
            assert reg.detect_best() == "python"

    def test_manual_override(self):
        reg = SearchEngineRegistry()
        reg.register(PythonSearchEngine())
        reg.set_default("python")
        engine = reg.get()
        assert engine.name == "python"

    def test_get_search_engine_singleton(self):
        engine = get_search_engine()
        assert engine.name in ("python", "ripgrep")
