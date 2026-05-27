"""Tests for iptables-style DontDo engine."""

import tempfile
from pathlib import Path

from agent.dont_do import DontDoEngine, HookPoint, Rule, Verdict


class TestDontDoEngine:
    def test_load_rules_from_yaml(self):
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "test.yaml").write_text("""
rules:
  - id: "r-001"
    description: "No deletes in production"
    hook: [PLAN, PRE_ACTION]
    match:
      object: database
      env: production
      operation: [DELETE, DROP]
    action: REJECT
    message: "No deletes in production"
""", encoding="utf-8")

            engine = DontDoEngine()
            count = engine.load_rules([d])
            assert count == 1
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_check_reject(self):
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "rules.yaml").write_text("""
rules:
  - id: "r-001"
    description: "Block"
    hook: [PRE_ACTION]
    match: {object: database, operation: DELETE}
    action: REJECT
    message: "Blocked"
""", encoding="utf-8")

            engine = DontDoEngine()
            engine.load_rules([d])
            verdict, msg = engine.check(HookPoint.PRE_ACTION, {
                "object": "database", "operation": "DELETE",
            })
            assert verdict == Verdict.REJECT
            assert "Blocked" in msg
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_check_allow(self):
        engine = DontDoEngine()
        engine.add_rule(Rule(
            id="r-allow-test", description="",
            hook=["PRE_ACTION"], match={"object": "database", "operation": "DELETE"},
            action="REJECT", message="No",
        ))
        verdict, msg = engine.check(HookPoint.PRE_ACTION, {
            "object": "file", "operation": "read",
        })
        assert verdict == Verdict.ALLOW

    def test_list_match(self):
        engine = DontDoEngine()
        engine.add_rule(Rule(
            id="r-list", description="",
            hook=["PRE_ACTION"],
            match={"operation": ["DELETE", "DROP"]},
            action="REJECT", message="Blocked",
        ))
        verdict, msg = engine.check(HookPoint.PRE_ACTION, {
            "operation": "DROP",
        })
        assert verdict == Verdict.REJECT

        verdict2, _ = engine.check(HookPoint.PRE_ACTION, {
            "operation": "SELECT",
        })
        assert verdict2 == Verdict.ALLOW

    def test_comparison_gt(self):
        engine = DontDoEngine()
        engine.add_rule(Rule(
            id="r-cmp", description="",
            hook=["PRE_ACTION"],
            match={"rows_affected_gt": 1000},
            action="WARN", message="Large delete",
        ))
        verdict, _ = engine.check(HookPoint.PRE_ACTION, {
            "rows_affected": 5000, "rows_affected_gt": 1000,
        })
        assert verdict == Verdict.WARN

    def test_first_match(self):
        engine = DontDoEngine()
        engine.add_rule(Rule(
            id="first", description="",
            hook=["PRE_ACTION"],
            match={"object": "database"},
            action="REJECT", message="First",
        ))
        engine.add_rule(Rule(
            id="second", description="",
            hook=["PRE_ACTION"],
            match={"object": "database"},
            action="WARN", message="Second",
        ))
        verdict, msg = engine.check(HookPoint.PRE_ACTION, {
            "object": "database",
        })
        assert msg == "First"

    def test_log_rule_continues_to_next(self):
        engine = DontDoEngine()
        engine.add_rule(Rule(
            id="audit", description="",
            hook=["PRE_ACTION"],
            match={"object": "database"},
            action="LOG", message="Audited",
        ))
        engine.add_rule(Rule(
            id="block", description="",
            hook=["PRE_ACTION"],
            match={"object": "database"},
            action="REJECT", message="Block",
        ))
        verdict, msg = engine.check(HookPoint.PRE_ACTION, {
            "object": "database",
        })
        assert verdict == Verdict.REJECT
        assert msg == "Block"

    def test_different_hooks(self):
        engine = DontDoEngine()
        engine.add_rule(Rule(
            id="plan-only", description="",
            hook=["PLAN"], match={"object": "file"},
            action="REJECT", message="Plan blocked",
        ))
        # This rule only fires on PLAN hook
        verdict, _ = engine.check(HookPoint.PRE_ACTION, {"object": "file"})
        assert verdict == Verdict.ALLOW

        verdict, _ = engine.check(HookPoint.PLAN, {"object": "file"})
        assert verdict == Verdict.REJECT
