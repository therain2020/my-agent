"""Tests for healing.py — fix database + error enrichment."""

from pathlib import Path

from therain2020.healing import HealingDB, Platform, _normalize_error


def test_platform_detect():
    p = Platform.detect()
    assert p.os in ("windows", "macos", "linux")
    assert p.which in ("where", "which")
    assert p.shell


def test_normalize_synonyms():
    assert _normalize_error("connection refused") == "daemon not running"
    assert _normalize_error("WebSocket error") == "daemon not running"
    assert _normalize_error("not recognized as internal") == "not found"
    assert _normalize_error("permissionerror") == "permission denied"


def test_unknown_error():
    result = _normalize_error("something completely unexpected happened here")
    assert len(result) <= 80


class TestHealingDB:
    def test_record_and_lookup(self, monkeypatch, tmp_path):
        monkeypatch.setattr("therain2020.healing.HEAL_PATH",
                           tmp_path / "heal.json")
        db = HealingDB()
        db.record("daemon not running",
                  "bash__run('start chrome --remote-debugging-port=9222')",
                  "browser")
        fix = db.lookup("daemon not running", "browser")
        assert fix is not None
        assert fix.confidence == 1.0

    def test_enrich_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr("therain2020.healing.HEAL_PATH",
                           tmp_path / "heal.json")
        db = HealingDB()
        db.record("daemon not running", "bash__run('fix')", "browser")
        enriched = db.enrich_error("daemon not running", "browser")
        assert "HEAL" in enriched
        assert "bash__run" in enriched

    def test_enrich_no_match(self, monkeypatch, tmp_path):
        monkeypatch.setattr("therain2020.healing.HEAL_PATH",
                           tmp_path / "heal.json")
        db = HealingDB()
        enriched = db.enrich_error("unknown error", "browser")
        assert "HEAL" not in enriched

    def test_lookup_returns_none_for_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr("therain2020.healing.HEAL_PATH",
                           tmp_path / "heal.json")
        db = HealingDB()
        assert db.lookup("nothing here") is None

    def test_remember_and_get_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr("therain2020.healing.HEAL_PATH",
                           tmp_path / "heal.json")
        db = HealingDB()
        chrome = str(tmp_path / "chrome.exe")
        Path(chrome).write_text("")
        db.remember_path("chrome", chrome)
        assert db.get_path("chrome") == chrome

    def test_persistence(self, monkeypatch, tmp_path):
        monkeypatch.setattr("therain2020.healing.HEAL_PATH",
                           tmp_path / "heal.json")
        db1 = HealingDB()
        db1.record("test error", "fix cmd", "bash")
        db1.save()

        db2 = HealingDB()
        db2.load()
        fix = db2.lookup("test error")
        assert fix is not None
        assert fix.command == "fix cmd"

    def test_context(self, monkeypatch, tmp_path):
        monkeypatch.setattr("therain2020.healing.HEAL_PATH",
                           tmp_path / "heal.json")
        db = HealingDB()
        db.record("daemon not running", "bash__run('fix')", "browser")
        for _ in range(3):
            db.record("daemon not running", "bash__run('fix')", "browser")
        ctx = db.context()
        assert "windows" in ctx.lower() or "macos" in ctx.lower() or "linux" in ctx.lower()
        assert "daemon not running" in ctx
