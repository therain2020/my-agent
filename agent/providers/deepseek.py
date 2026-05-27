"""DeepSeek provider adapter. DeepSeek API is OpenAI-compatible."""

from .openai import OpenAIProvider
from . import ProviderConfig


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek API adapter. Uses OpenAI SDK with DeepSeek base URL."""

    def __init__(self, config: ProviderConfig):
        if not config.base_url:
            config.base_url = "https://api.deepseek.com/v1"
        super().__init__(config)

    @property
    def context_window(self) -> int:
        return 65536  # deepseek-chat

    def token_count(self, text: str) -> int:
        return len(text) // 4  # DeepSeek doesn't have a public tokenizer
