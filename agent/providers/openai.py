"""OpenAI / openai-compatible provider adapter."""

import os
from typing import AsyncIterator

import openai
import structlog

from . import LLMResponse, ProviderConfig

logger = structlog.get_logger()


class OpenAIProvider:
    """OpenAI API adapter. Also works as base for openai-compatible providers."""

    def __init__(self, config: ProviderConfig):
        self._config = config
        api_key = config.api_key or os.getenv(config.api_key_env, "")
        base_url = config.base_url or None

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        if not api_key:
            raise ValueError(
                f"OpenAI API key not found. "
                f"Set {config.api_key_env} or provide api_key in config."
            )
        self._client = openai.AsyncOpenAI(**client_kwargs)
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
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16384,
        }
        for prefix, size in windows.items():
            if self._model.startswith(prefix):
                return size
        return 128000

    def token_count(self, text: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(self._model)
            return len(enc.encode(text))
        except Exception:
            return len(text) // 4

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        max_tokens = kwargs.pop("max_tokens", 4096)
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                **kwargs,
            )
        except Exception as e:
            logger.error("openai_api_error", error=str(e))
            raise self._classify_error(e) from e

        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            content=choice.message.content or "",
            model=self._model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            provider_name=self.name,
        )

    async def complete_stream(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        max_tokens = kwargs.pop("max_tokens", 4096)
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error("openai_stream_error", error=str(e))
            raise self._classify_error(e) from e

    def _classify_error(self, error: Exception) -> Exception:
        from agent.errors import (
            ProviderAuthError,
            ProviderBadRequestError,
            ProviderRateLimitError,
            ProviderServerError,
            ProviderTimeoutError,
        )
        import httpx
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
