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


# ——— Centralized exception handler ———


def format_error_for_llm(error: Exception, sanitize: bool = True) -> str:
    """Convert an agent exception into a message safe for LLM consumption.

    Three-layer pattern (from layered-exception-handling.md):
    1. Raise layer: code raises typed AgentError subclasses
    2. Catch layer: this function translates to LLM-friendly messages
    3. Sanitize layer: removes internal paths, stack traces, sensitive info

    Args:
        error: The caught exception.
        sanitize: If True, strip internal details before returning.

    Returns:
        A string suitable for appending to the agent's conversation.
    """
    if isinstance(error, DontDoViolation):
        return f"[Blocked] Rule {error.rule_id}: {_sanitize(str(error), sanitize)}"

    if isinstance(error, ToolExecutionError):
        msg = f"[Tool Error] {error.tool_name} (exit {error.exit_code})"
        if error.stderr and not sanitize:
            msg += f": {error.stderr[:200]}"
        return msg

    if isinstance(error, ToolTimeoutError):
        return f"[Timeout] {error.tool_name} exceeded {error.timeout}s"

    if isinstance(error, ToolNotFoundError):
        return f"[Not Found] {_sanitize(str(error), sanitize)}"

    if isinstance(error, ToolAccessDenied):
        return f"[Access Denied] {_sanitize(str(error), sanitize)}"

    if isinstance(error, ProviderAuthError):
        return "[Provider Error] Authentication failed — check API key"

    if isinstance(error, ProviderRateLimitError):
        return "[Provider Error] Rate limit reached — retry after delay"

    if isinstance(error, ProviderTimeoutError):
        return "[Provider Error] Request timed out — retrying"

    if isinstance(error, ProviderServerError):
        return "[Provider Error] Server error — will retry"

    if isinstance(error, ProviderError):
        return f"[Provider Error] {_sanitize(str(error), sanitize)}"

    if isinstance(error, LoopExhaustedError):
        return (
            f"[Exhausted] Task {error.task_id} did not complete "
            f"within {error.iterations} iterations"
        )

    if isinstance(error, InterruptSignal):
        return "[Interrupted] Task cancelled by user"

    if isinstance(error, AgentError):
        return f"[Error] {_sanitize(str(error), sanitize)}"

    # Unknown exception — sanitize aggressively
    if sanitize:
        return f"[Error] {type(error).__name__}"
    return f"[Error] {type(error).__name__}: {str(error)[:200]}"


def _sanitize(text: str, enabled: bool) -> str:
    """Remove sensitive/internal details from error text."""
    if not enabled:
        return text
    # Replace file paths with basename
    import re
    text = re.sub(r'[A-Za-z]:\\[^\s,;:"]+\\', '.../', text)
    text = re.sub(r'/[^\s,;:"]+/', '.../', text)
    return text[:300]

