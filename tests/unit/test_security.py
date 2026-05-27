"""Tests for security manager."""

import tempfile
from pathlib import Path

from agent.security import SecurityManager


class TestSecurityManager:
    def test_load_rules_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SecurityManager(dont_do_paths=[tmp])
            count = mgr.load_rules()
            assert count == 0

    def test_load_rules_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            rule_dir = Path(tmp)
            (rule_dir / "test.md").write_text("# Test Rule\n- Do not do X", encoding="utf-8")

            mgr = SecurityManager(dont_do_paths=[str(rule_dir)])
            count = mgr.load_rules()
            assert count == 1
            assert "test" in mgr.list_rules()

    def test_get_constraints_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            rule_dir = Path(tmp)
            (rule_dir / "database.md").write_text("# DB Rules\nNo DROP in production", encoding="utf-8")

            mgr = SecurityManager(dont_do_paths=[str(rule_dir)])
            mgr.load_rules()

            prompt = mgr.get_constraints_prompt()
            assert "No DROP" in prompt

    def test_filter_by_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            rule_dir = Path(tmp)
            (rule_dir / "database.md").write_text("DB rules", encoding="utf-8")
            (rule_dir / "file-system.md").write_text("FS rules", encoding="utf-8")

            mgr = SecurityManager(dont_do_paths=[str(rule_dir)])
            mgr.load_rules()

            db_prompt = mgr.get_constraints_prompt(relevant_objects=["database"])
            assert "DB rules" in db_prompt
            assert "FS rules" not in db_prompt

    def test_add_rule(self):
        mgr = SecurityManager(dont_do_paths=["./nonexistent"])
        with tempfile.TemporaryDirectory() as tmp:
            mgr.add_rule("new-rule", "New rule content", Path(tmp))
            rules = mgr.list_rules()
            assert "new-rule" in rules
            assert (Path(tmp) / "new-rule.md").exists()
