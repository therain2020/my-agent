"""Tests for Phase 3: correction system and TODO analysis."""

import tempfile
from pathlib import Path

import yaml

from agent.correction import (
    Correction,
    CorrectionSource,
    Severity,
    parse_correction_file,
    persist_dont_do_rule,
)
from agent.dont_do import Rule


class TestCorrection:
    def test_defaults(self):
        c = Correction(
            id="c-1", timestamp="t", source=CorrectionSource.USER,
            target_uri="file://test.py",
        )
        assert c.applied is False
        assert c.severity == Severity.BLOCKER
        assert c.generated_rule_id is None

    def test_to_context(self):
        c = Correction(
            id="c-1", timestamp="t", source=CorrectionSource.USER,
            target_uri="file://test.py", issue_type="wrong_action",
            description="Don't delete config files",
        )
        ctx = c.to_context()
        assert ctx["object"] == "file://test.py"
        assert ctx["issue"] == "wrong_action"

    def test_parse_correction_file(self):
        d = tempfile.mkdtemp()
        try:
            path = Path(d) / "corr.yaml"
            content = {
                "id": "corr-001",
                "target": "file://test.py",
                "step": "delete config",
                "issue_type": "wrong_action",
                "description": "Should not delete config files",
                "suggestion": "Modify instead of delete",
                "severity": "blocker",
            }
            path.write_text(yaml.dump(content), encoding="utf-8")
            c = parse_correction_file(path)
            assert c is not None
            assert c.id == "corr-001"
            assert c.target_uri == "file://test.py"
            assert c.issue_type == "wrong_action"
            assert c.severity == Severity.BLOCKER
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_parse_correction_file_missing_target(self):
        d = tempfile.mkdtemp()
        try:
            path = Path(d) / "bad.yaml"
            path.write_text("description: no target\n", encoding="utf-8")
            c = parse_correction_file(path)
            assert c is None
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class TestPersistDontDoRule:
    def test_persist_new_file(self):
        d = tempfile.mkdtemp()
        try:
            rule = Rule(
                id="corr-test-001",
                description="Do not delete system files",
                hook=["PRE_ACTION"],
                match={"object": "file", "operation": "delete_file"},
                action="REJECT",
                message="Deleting system files is forbidden",
                source="correction:c-1",
            )
            path = persist_dont_do_rule(rule, base_dir=d)
            assert path.exists()
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert len(data["rules"]) == 1
            assert data["rules"][0]["id"] == "corr-test-001"
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_persist_appends_to_existing(self):
        d = tempfile.mkdtemp()
        try:
            # Pre-create a rule file
            obj_dir = Path(d) / "file"
            obj_dir.mkdir(parents=True)
            existing_path = obj_dir / "file.yaml"
            existing_path.write_text(yaml.dump({
                "rules": [{"id": "existing-rule", "description": "Old rule",
                           "hook": ["PRE_ACTION"], "match": {}, "action": "REJECT",
                           "message": "Old"}],
            }), encoding="utf-8")

            rule = Rule(
                id="corr-test-002",
                description="New rule appended",
                hook=["POST_ACTION"],
                match={"object": "file"},
                action="WARN",
                message="New",
                source="correction:c-2",
            )
            path = persist_dont_do_rule(rule, base_dir=d)
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert len(data["rules"]) == 2
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
