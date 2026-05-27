"""LLM Provider abstraction (HAL). 类比: Kernel Hardware Abstraction Layer."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    """Standardized LLM response."""
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    provider_name: str = ""


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""
    name: str
    model: str
    api_key_env: str = ""
    api_key: str = ""  # Resolved value, not from config
    base_url: str = ""  # For openai-compatible providers (deepseek, local, etc.)
    priority: str = "primary"  # primary | fallback | last_resort
    max_retries: int = 5
    timeout: float = 120.0
    extra: dict = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """Unified LLM interface. 类比: HAL cpu_ops.

    All provider adapters implement this Protocol.
    No need to subclass — structural typing via Protocol.
    """

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """Send a prompt and get a complete response."""
        ...

    async def complete_stream(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        """Send a prompt and get a streaming response."""
        ...

    def token_count(self, text: str) -> int:
        """Estimate token count for the given text."""
        ...

    @property
    def context_window(self) -> int:
        """Maximum context window size in tokens."""
        ...
