"""Error types for the Agent system."""


class AgentError(Exception):
    """Base exception for all agent errors."""
    pass


class ConfigError(AgentError):
    """Configuration loading or validation error."""
    pass


class ProviderError(AgentError):
    """LLM Provider related error."""
    pass


class ProviderAuthError(ProviderError):
    """Authentication failure (401)."""
    pass


class ProviderRateLimitError(ProviderError):
    """Rate limit (429)."""
    pass


class ProviderServerError(ProviderError):
    """Server-side error (5xx)."""
    pass


class ProviderTimeoutError(ProviderError):
    """Request timeout."""
    pass


class ProviderBadRequestError(ProviderError):
    """Bad request (4xx, not 401/429)."""
    pass


class ToolError(AgentError):
    """Tool related error."""
    pass


class ToolNotFoundError(ToolError):
    """Requested tool not found."""
    pass


class ToolExecutionError(ToolError):
    """Tool execution failed."""
    def __init__(self, tool_name: str, exit_code: int, stderr: str):
        self.tool_name = tool_name
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"{tool_name} failed (exit {exit_code}): {stderr}")


class ToolTimeoutError(ToolError):
    """Tool execution timed out."""
    def __init__(self, tool_name: str, timeout: float):
        self.tool_name = tool_name
        self.timeout = timeout
        super().__init__(f"{tool_name} timed out after {timeout}s")


class ToolAccessDenied(ToolError):
    """Tool access denied by security check."""
    pass


class DontDoViolation(AgentError):
    """A dont-do rule was triggered."""
    def __init__(self, rule_id: str, message: str):
        self.rule_id = rule_id
        super().__init__(message)


class SecurityError(AgentError):
    """Security related error."""
    pass


class ImportError_(AgentError):
    """Adapter import error (avoid shadowing builtin ImportError)."""
    pass


class ImportValidationError(ImportError_):
    """Import validation failed."""
    pass


class MemoryError(AgentError):
    """Memory storage error."""
    pass


class InterruptSignal(AgentError):
    """User interrupted execution."""
    pass


class LoopExhaustedError(AgentError):
    """Task exceeded maximum loop iterations."""
    def __init__(self, task_id: str, iterations: int):
        self.task_id = task_id
        self.iterations = iterations
        super().__init__(f"Task {task_id} exhausted after {iterations} iterations")


class TransientError(AgentError):
    """Base class for errors that can be retried."""
    pass


class FatalError(AgentError):
    """Base class for errors that should NOT be retried."""
    pass


class CircuitBreakerOpenError(AgentError):
    """Circuit breaker is open, request rejected."""
    pass
