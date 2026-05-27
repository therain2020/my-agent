"""Custom provider for any openai-compatible endpoint."""

from . import ProviderConfig
from .openai import OpenAIProvider


class CustomProvider(OpenAIProvider):
    """Generic openai-compatible provider.

    Use for: Ollama, vLLM, LiteLLM, local models, and any
    API that speaks the OpenAI chat completions format.
    """

    def __init__(self, config: ProviderConfig):
        if not config.base_url:
            raise ValueError(
                "Custom provider requires --base-url. "
                "Example: therain2020-agent provider add custom --base-url http://localhost:11434/v1"
            )
        super().__init__(config)

    @property
    def context_window(self) -> int:
        return self._config.extra.get("context_window", 128000)
