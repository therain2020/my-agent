"""Tests for verification hooks in tool executor (十-A)."""

import pytest

from agent.tools.executor import VerificationResult


class TestVerificationResult:
    def test_verified_success(self):
        vr = VerificationResult(
            verified=True,
            expected_effect="File created",
            actual_state={"exists": True, "size": 100},
            expected_state={"exists": True, "size": 100},
        )
        assert vr.verified
        assert vr.diff == {}

    def test_verified_failure_with_diff(self):
        vr = VerificationResult(
            verified=False,
            expected_effect="File created",
            actual_state={"exists": False},
            expected_state={"exists": True},
            suggestion="Check directory permissions",
        )
        assert not vr.verified
        assert vr.diff == {"exists": {"expected": True, "actual": False}}
        assert vr.suggestion == "Check directory permissions"

    def test_partial_diff(self):
        vr = VerificationResult(
            verified=False,
            expected_effect="Content written",
            actual_state={"size": 0, "hash": "abc"},
            expected_state={"size": 100, "hash": "def"},
        )
        diff = vr.diff
        assert len(diff) == 2
        assert diff["size"] == {"expected": 100, "actual": 0}

    def test_defaults(self):
        vr = VerificationResult(verified=True)
        assert vr.expected_effect == ""
        assert vr.actual_state == {}
        assert vr.expected_state == {}
        assert vr.suggestion is None
        assert vr.diff == {}
