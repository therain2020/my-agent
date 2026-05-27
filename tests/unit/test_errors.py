"""Tests for error type hierarchy."""

from agent.errors import (
    AgentError,
    ConfigError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
    ProviderBadRequestError,
    ToolNotFoundError,
    ToolExecutionError,
    ToolTimeoutError,
    ToolAccessDenied,
    DontDoViolation,
    ImportError_,
    ImportValidationError,
    LoopExhaustedError,
    InterruptSignal,
    TransientError,
    FatalError,
    CircuitBreakerOpenError,
)


class TestErrorHierarchy:
    def test_all_errors_inherit_from_agent_error(self):
        errors = [
            ConfigError("test"),
            ProviderAuthError("test"),
            ToolNotFoundError("test"),
            DontDoViolation("r-001", "test"),
            LoopExhaustedError("t1", 3),
            InterruptSignal("test"),
        ]
        for e in errors:
            assert isinstance(e, AgentError)

    def test_transient_vs_fatal(self):
        timeout = ProviderTimeoutError("timeout")
        auth = ProviderAuthError("unauthorized")

        assert isinstance(timeout, TransientError) is False  # provider errors are not auto-transient
        assert isinstance(auth, TransientError) is False

    def test_tool_execution_error_has_context(self):
        e = ToolExecutionError("test-tool", 1, "stderr output")
        assert e.tool_name == "test-tool"
        assert e.exit_code == 1
        assert "stderr output" in str(e)

    def test_tool_timeout_error(self):
        e = ToolTimeoutError("slow-tool", 30.0)
        assert e.tool_name == "slow-tool"
        assert e.timeout == 30.0

    def test_loop_exhausted_error(self):
        e = LoopExhaustedError("task-42", 3)
        assert e.task_id == "task-42"
        assert e.iterations == 3

    def test_dont_do_violation(self):
        e = DontDoViolation("r-0042", "Prohibited operation")
        assert e.rule_id == "r-0042"


class TestRetryClassification:
    def test_auth_errors_not_retryable(self):
        from agent.retry import RetryPolicy
        policy = RetryPolicy()
        assert policy.should_retry(ProviderAuthError("bad key"), 0) is False

    def test_bad_request_not_retryable(self):
        from agent.retry import RetryPolicy
        policy = RetryPolicy()
        assert policy.should_retry(ProviderBadRequestError("bad"), 0) is False

    def test_rate_limit_is_retryable(self):
        from agent.retry import RetryPolicy
        policy = RetryPolicy(max_retries=3)
        assert policy.should_retry(ProviderRateLimitError("slow"), 0) is True

    def test_exceeds_max_retries(self):
        from agent.retry import RetryPolicy
        policy = RetryPolicy(max_retries=3)
        assert policy.should_retry(ProviderServerError("err"), 3) is False

    def test_delay_increases(self):
        from agent.retry import RetryPolicy
        policy = RetryPolicy(initial_delay=1.0, multiplier=2.0, jitter=False)
        d0 = policy.delay_for(0)
        d1 = policy.delay_for(1)
        d2 = policy.delay_for(2)
        assert d0 == 1.0
        assert d1 == 2.0
        assert d2 == 4.0
