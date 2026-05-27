"""Anthropic provider adapter."""

import os
from collections.abc import AsyncIterator

import structlog

from . import LLMResponse, ProviderConfig

logger = structlog.get_logger()


class AnthropicProvider:
    """Anthropic Claude API adapter."""

    def __init__(self, config: ProviderConfig):
        self._config = config
        api_key = config.api_key or os.getenv(config.api_key_env, "")
        if not api_key:
            raise ValueError(
                f"Anthropic API key not found. "
                f"Set {config.api_key_env} or provide api_key in config."
            )
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = config.model

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def model(self) -> str:
        return self._model

    @property
    def context_window(self) -> int:
        windows = {
            "claude-opus-4-7": 200000,
            "claude-sonnet-4-6": 200000,
            "claude-haiku-4-5": 200000,
        }
        for prefix, size in windows.items():
            if self._model.startswith(prefix):
                return size
        return 200000

    def token_count(self, text: str) -> int:
        import anthropic
        try:
            return anthropic.count_tokens(text)
        except Exception:
            return len(text) // 4

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        max_tokens = kwargs.pop("max_tokens", 4096)
        try:
            msg = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )
        except Exception as e:
            logger.error("anthropic_api_error", error=str(e))
            raise self._classify_error(e) from e

        return LLMResponse(
            content=msg.content[0].text,
            model=self._model,
            prompt_tokens=msg.usage.input_tokens,
            completion_tokens=msg.usage.output_tokens,
            total_tokens=msg.usage.input_tokens + msg.usage.output_tokens,
            provider_name=self.name,
        )

    async def complete_stream(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        max_tokens = kwargs.pop("max_tokens", 4096)
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error("anthropic_stream_error", error=str(e))
            raise self._classify_error(e) from e

    def _classify_error(self, error: Exception) -> Exception:
        import httpx

        from agent.errors import (
            ProviderAuthError,
            ProviderBadRequestError,
            ProviderRateLimitError,
            ProviderServerError,
            ProviderTimeoutError,
        )
        status = getattr(error, "status_code", 0)
        if status == 401:
            return ProviderAuthError(str(error))
        if status == 429:
            return ProviderRateLimitError(str(error))
        if status == 400:
            return ProviderBadRequestError(str(error))
        if status and status >= 500:
            return ProviderServerError(str(error))
        if isinstance(error, httpx.TimeoutException):
            return ProviderTimeoutError(str(error))
        return error
