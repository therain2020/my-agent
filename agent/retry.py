"""Exponential backoff retry. 类比: TCP retransmission."""

import asyncio
import random
import time
from typing import Callable, TypeVar

import structlog

from .errors import FatalError, TransientError

logger = structlog.get_logger()
T = TypeVar("T")


class RetryPolicy:
    """Exponential backoff with jitter. 类比: TCP RTO calculation."""

    def __init__(
        self,
        max_retries: int = 5,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        multiplier: float = 2.0,
        jitter: bool = True,
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter

    def delay_for(self, attempt: int) -> float:
        base = self.initial_delay * (self.multiplier ** attempt)
        capped = min(base, self.max_delay)
        if self.jitter:
            return capped * (0.5 + random.random())
        return capped

    def should_retry(self, error: Exception, attempt: int) -> bool:
        """Determine if this error should be retried.

        类比: TCP does not retry on ICMP Destination Unreachable.
        We don't retry on auth errors (4xx) but do on transient issues.
        """
        from .errors import (
            ProviderAuthError,
            ProviderBadRequestError,
            ProviderRateLimitError,
            ProviderServerError,
            ProviderTimeoutError,
        )

        if isinstance(error, FatalError):
            return False
        if isinstance(error, (ProviderAuthError, ProviderBadRequestError)):
            return False
        if isinstance(error, (ProviderRateLimitError, ProviderServerError,
                              ProviderTimeoutError, TransientError)):
            return attempt < self.max_retries
        return attempt < self.max_retries


DEFAULT_RETRY = RetryPolicy()


async def retry(
    fn: Callable[..., T],
    *args,
    policy: RetryPolicy = DEFAULT_RETRY,
    context: dict | None = None,
    **kwargs,
) -> T:
    """Execute fn with exponential backoff retry.

    Never retries on auth errors (4xx). Retries on rate limits,
    server errors, and timeouts with exponential backoff.
    """
    last_error = None
    for attempt in range(policy.max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except FatalError:
            raise
        except Exception as e:
            last_error = e
            if not policy.should_retry(e, attempt):
                raise

            delay = policy.delay_for(attempt)
            logger.warning(
                "retry_attempt",
                attempt=attempt + 1,
                max_retries=policy.max_retries,
                delay_seconds=round(delay, 2),
                error_type=type(e).__name__,
                error=str(e)[:200],
                context=context,
            )
            await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]
