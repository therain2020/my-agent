"""Tests for safety.py — unified dont-do engine."""

import pytest

from therain2020.safety import (
    HookPoint,
    Rule,
    SafetyEngine,
    Verdict,
)


@pytest.fixture
def engine():
    return SafetyEngine()


class TestBuiltinRules:
    def test_restricted_path_blocked(self, engine):
        result = engine.check(
            HookPoint.PRE_ACTION,
            {
                "tool": "write_file",
                "params": {"path": "/etc/passwd", "content": "x"},
            },
        )
        assert result.verdict == Verdict.REJECT

    def test_allow_normal_path(self, engine):
        result = engine.check(
            HookPoint.PRE_ACTION,
            {
                "tool": "write_file",
                "params": {"path": "/home/user/test.txt", "content": "x"},
            },
        )
        assert result.verdict == Verdict.ALLOW

    def test_sensitive_file_warns(self, engine):
        result = engine.check(
            HookPoint.PRE_ACTION,
            {
                "tool": "read_file",
                "params": {"path": "/home/user/.env", "content": "x"},
            },
        )
        assert result.verdict == Verdict.WARN

    def test_irrelevant_hook_ignored(self, engine):
        result = engine.check(
            HookPoint.PLAN,
            {"tool": "write_file", "params": {"path": "/etc/passwd"}},
        )
        assert result.verdict == Verdict.ALLOW  # builtin rules only hook PRE_ACTION


class TestCustomRules:
    @pytest.fixture
    def engine_with_custom(self):
        eng = SafetyEngine()
        eng.add_rule(Rule(
            id="test:always-reject",
            description="test",
            hooks=[HookPoint.PRE_ACTION, HookPoint.POST_ACTION],
            match={"tool": "dangerous_tool"},
            action=Verdict.REJECT,
            message="No.",
        ))
        eng.add_rule(Rule(
            id="test:log-only",
            description="test",
            hooks=[HookPoint.PRE_ACTION],
            match={"tool": "logging_tool"},
            action=Verdict.LOG,
            message="Note.",
        ))
        return eng

    def test_custom_reject(self, engine_with_custom):
        result = engine_with_custom.check(
            HookPoint.PRE_ACTION,
            {"tool": "dangerous_tool"},
        )
        assert result.verdict == Verdict.REJECT
        assert result.rule_id == "test:always-reject"

    def test_log_passes_through(self, engine_with_custom):
        result = engine_with_custom.check(
            HookPoint.PRE_ACTION,
            {"tool": "logging_tool"},
        )
        assert result.verdict == Verdict.ALLOW  # LOG continues to next rule

    def test_first_match_wins(self, engine_with_custom):
        result = engine_with_custom.check(
            HookPoint.PRE_ACTION,
            {"tool": "dangerous_tool"},
        )
        assert result.rule_id == "test:always-reject"


class TestYAMLRuleLoading:
    def test_load_from_dir(self, tmp_path):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "test.yaml").write_text("""
rules:
  - id: yaml:block-delete
    description: Block delete on etc
    hooks: [PRE_ACTION]
    match:
      tool: delete_file
      params.path_glob: /etc/*
    action: REJECT
    message: Cannot delete system files
""", encoding="utf-8")
        eng = SafetyEngine(rules_dir=rules_dir)
        result = eng.check(
            HookPoint.PRE_ACTION,
            {"tool": "delete_file", "params": {"path": "/etc/hosts"}},
        )
        assert result.verdict == Verdict.REJECT

    def test_load_from_empty_dir(self, tmp_path):
        rules_dir = tmp_path / "empty"
        rules_dir.mkdir()
        eng = SafetyEngine(rules_dir=rules_dir)
        # builtins still loaded
        result = eng.check(
            HookPoint.PRE_ACTION,
            {"tool": "write_file", "params": {"path": "/etc/hosts"}},
        )
        assert result.verdict == Verdict.REJECT


class TestMatching:
    def test_exact_match(self, engine):
        engine.add_rule(Rule(
            id="t", description="", hooks=[HookPoint.PRE_ACTION],
            match={"tool": "rm"}, action=Verdict.REJECT,
        ))
        assert engine.check(HookPoint.PRE_ACTION, {"tool": "rm"}).verdict == Verdict.REJECT
        assert engine.check(HookPoint.PRE_ACTION, {"tool": "ls"}).verdict == Verdict.ALLOW

    def test_list_match(self, engine):
        engine.add_rule(Rule(
            id="t", description="", hooks=[HookPoint.PRE_ACTION],
            match={"tool": ["rm", "delete"]}, action=Verdict.REJECT,
        ))
        assert engine.check(HookPoint.PRE_ACTION, {"tool": "delete"}).verdict == Verdict.REJECT
        assert engine.check(HookPoint.PRE_ACTION, {"tool": "cp"}).verdict == Verdict.ALLOW

    def test_glob_match(self, engine):
        engine.add_rule(Rule(
            id="t", description="", hooks=[HookPoint.PRE_ACTION],
            match={"params.path_glob": "/secret/*"}, action=Verdict.REJECT,
        ))
        assert engine.check(
            HookPoint.PRE_ACTION, {"tool": "r", "params": {"path": "/secret/key"}},
        ).verdict == Verdict.REJECT
        assert engine.check(
            HookPoint.PRE_ACTION, {"tool": "r", "params": {"path": "/public"}},
        ).verdict == Verdict.ALLOW

    def test_comparison_match(self, engine):
        engine.add_rule(Rule(
            id="t", description="", hooks=[HookPoint.PRE_ACTION],
            match={"params.size_gt": 100}, action=Verdict.REJECT,
        ))
        assert engine.check(
            HookPoint.PRE_ACTION, {"tool": "w", "params": {"size": 200}},
        ).verdict == Verdict.REJECT
        assert engine.check(
            HookPoint.PRE_ACTION, {"tool": "w", "params": {"size": 50}},
        ).verdict == Verdict.ALLOW
