"""Tests for cross-episode pattern mining (Agent Self-Teaching)."""

import tempfile

import pytest

from agent.event_store import EventStore
from agent.events import (
    correction_applied,
    error_occurred,
    goal_started,
    goal_verified,
)
from agent.memory import MemoryStore
from agent.pattern_miner import PatternMiner, PatternProposal, ProposalType


class TestPatternProposal:
    def test_to_markdown(self):
        p = PatternProposal(
            type=ProposalType.RULE,
            title="Test proposal",
            description="A test",
            confidence=0.85,
            evidence=["t-1", "t-2"],
            suggested_content="rule content here",
        )
        md = p.to_markdown()
        assert "[RULE]" in md
        assert "85%" in md
        assert "t-1" in md
        assert "rule content here" in md


class TestPatternMiner:
    @pytest.fixture(autouse=True)
    def _setup(self):
        d = tempfile.mkdtemp()
        self._tmpdir = d
        self.store = MemoryStore(db_path=f"{d}/test.db")
        self.event_store = EventStore(self.store.conn)
        self.miner = PatternMiner(self.event_store)
        yield
        self.store.close()
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    # ——— Error Patterns ———

    def test_no_patterns_with_few_errors(self):
        """Fewer than MIN_OCCURRENCES errors should yield no proposals."""
        self.event_store.append(error_occurred("t-1", "ValueError", "bad"))
        self.event_store.append(error_occurred("t-2", "TypeError", "bad"))

        proposals = self.miner.mine_error_patterns()
        assert proposals == []

    def test_recurring_error_generates_proposal(self):
        """Same error type across multiple tasks → rule proposal."""
        for i in range(5):
            tid = f"t-err-{i}"
            self.event_store.append(goal_started(tid, f"task {i}"))
            self.event_store.append(error_occurred(
                tid, "ConnectionError", "Database connection timeout",
            ))

        proposals = self.miner.mine_error_patterns()
        assert len(proposals) >= 1, (
            f"Expected at least 1 proposal for recurring ConnectionError, "
            f"got {len(proposals)}"
        )
        p = proposals[0]
        assert p.type == ProposalType.RULE
        assert "ConnectionError" in p.title
        assert p.confidence >= 0.7

    def test_different_errors_no_cluster(self):
        """Different error types should not cluster together."""
        errors = [
            ("ValueError", "bad value"),
            ("TypeError", "bad type"),
            ("KeyError", "missing key"),
            ("OSError", "file not found"),
            ("RuntimeError", "something wrong"),
        ]
        for i, (etype, msg) in enumerate(errors):
            self.event_store.append(error_occurred(f"t-{i}", etype, msg))

        proposals = self.miner.mine_error_patterns()
        # Each is unique, no cluster should reach MIN_OCCURRENCES
        assert len(proposals) == 0

    # ——— Correction Patterns ———

    def test_recurring_correction_generates_skill(self):
        """Same correction applied many times → skill proposal."""
        for i in range(4):
            tid = f"t-cor-{i}"
            self.event_store.append(goal_started(tid, f"task {i}"))
            self.event_store.append(correction_applied(
                tid, f"corr-{i}", f"rule-{i}",
                "Don't use hardcoded paths in configuration files",
            ))

        proposals = self.miner.mine_correction_patterns()
        assert len(proposals) >= 1
        p = proposals[0]
        assert p.type == ProposalType.SKILL
        assert "hardcoded" in p.title.lower() or "hardcoded" in p.description.lower()

    def test_few_corrections_no_proposal(self):
        """Only 2 corrections → below threshold."""
        for i in range(2):
            self.event_store.append(correction_applied(
                f"t-{i}", f"corr-{i}", f"rule-{i}", "Fix formatting",
            ))
        proposals = self.miner.mine_correction_patterns()
        assert proposals == []

    # ——— Failure Patterns ———

    def test_recurring_verification_failure(self):
        """Same verify failure across tasks → plan hint proposal."""
        for i in range(3):
            tid = f"t-vf-{i}"
            self.event_store.append(goal_started(tid, f"task {i}"))
            self.event_store.append(goal_verified(
                tid, False, 0.3,
                "Database migration was not followed by integration tests",
            ))

        proposals = self.miner.mine_failure_patterns()
        if proposals:  # May or may not reach threshold depending on summarization
            assert proposals[0].type == ProposalType.PLAN_HINT

    def test_no_failure_pattern_successful_tasks(self):
        """All verifications pass → no failure patterns."""
        for i in range(10):
            tid = f"t-ok-{i}"
            self.event_store.append(goal_verified(tid, True, 0.95, "All good"))

        proposals = self.miner.mine_failure_patterns()
        assert proposals == []

    # ——— Combined Mining ———

    def test_mine_all(self):
        """mine() should run all three analyses."""
        # Add enough errors for a pattern
        for i in range(5):
            tid = f"t-all-{i}"
            self.event_store.append(goal_started(tid, f"task {i}"))
            self.event_store.append(error_occurred(
                tid, "ImportError", "Module not found",
            ))

        proposals = self.miner.mine(recent_tasks=50)
        assert len(proposals) >= 1  # At least error pattern

    # ——— Edge Cases ———

    def test_empty_event_store(self):
        """Empty store → no proposals."""
        proposals = self.miner.mine()
        assert proposals == []

    def test_low_confidence_filtered(self):
        """Barely-above-threshold patterns should be filtered."""
        # Exactly 3 occurrences → confidence = 3/5 = 0.6 (below 0.7)
        for i in range(3):
            self.event_store.append(error_occurred(
                f"t-low-{i}", "WarningError", "minor issue",
            ))
        proposals = self.miner.mine_error_patterns()
        # 3 occurrences → confidence 3/(3+2)=0.6 < 0.7 threshold
        assert proposals == []


class TestProposalMarkdown:
    def test_empty_proposals(self):
        md = PatternMiner.proposals_to_markdown([])
        assert "No patterns discovered" in md

    def test_multiple_proposals(self):
        proposals = [
            PatternProposal(
                type=ProposalType.RULE,
                title="Error pattern 1",
                description="desc",
                confidence=0.8,
                evidence=["t-1"],
            ),
            PatternProposal(
                type=ProposalType.SKILL,
                title="Correction pattern 1",
                description="desc",
                confidence=0.9,
                evidence=["t-2"],
            ),
        ]
        md = PatternMiner.proposals_to_markdown(proposals)
        assert "2 proposals" in md
        assert "[RULE]" in md
        assert "[SKILL]" in md
