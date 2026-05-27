"""Tests for evaluation framework (no real LLM required)."""

from agent.eval import (
    STANDARD_SUITE,
    EvalReport,
    EvalResult,
    Severity,
)


class TestEvalSuite:
    def test_standard_suite_has_cases(self):
        assert len(STANDARD_SUITE) >= 4

    def test_critical_cases_exist(self):
        critical = [c for c in STANDARD_SUITE if c.severity == Severity.CRITICAL]
        assert len(critical) >= 1

    def test_all_cases_have_ids(self):
        ids = [c.id for c in STANDARD_SUITE]
        assert len(ids) == len(set(ids))  # No duplicate IDs


class TestEvalReport:
    def test_all_pass(self):
        results = [
            EvalResult(case_id="a", passed=True, actual_steps=1,
                       actual_tools=[], actual_llm_calls=2, duration_seconds=1.0),
            EvalResult(case_id="b", passed=True, actual_steps=2,
                       actual_tools=[], actual_llm_calls=3, duration_seconds=2.0),
        ]
        report = EvalReport(results=results, total=2, passed=2, failed=0)
        assert report.pass_rate == 100.0

    def test_mixed_results(self):
        results = [
            EvalResult(case_id="a", passed=True, actual_steps=1,
                       actual_tools=[], actual_llm_calls=1, duration_seconds=1.0),
            EvalResult(case_id="b", passed=False, actual_steps=5,
                       actual_tools=[], actual_llm_calls=3, duration_seconds=3.0),
        ]
        report = EvalReport(results=results, total=2, passed=1, failed=1)
        assert report.pass_rate == 50.0
