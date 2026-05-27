"""Provider pool with failover. 类比: RAID 1 + multipath I/O."""

import time

import structlog

from agent.providers import LLMProvider, LLMResponse

logger = structlog.get_logger()


class CircuitBreaker:
    """Circuit breaker for provider calls. 类比: electrical circuit breaker.

    CLOSED → 5 failures → OPEN (30s) → HALF-OPEN (probe) → CLOSED or OPEN
    """

    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: float = 0
        self.state = "CLOSED"

    async def call(self, fn, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info("circuit_breaker_half_open", name=self.name)
            else:
                remaining = self.recovery_timeout - (time.time() - self.last_failure_time)
                raise CircuitBreakerOpenError(
                    f"{self.name} circuit breaker open, {remaining:.0f}s remaining"
                )

        try:
            result = await fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _on_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.state in ("CLOSED", "HALF_OPEN") and self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning("circuit_breaker_open", name=self.name,
                           failures=self.failure_count)


class CircuitBreakerOpenError(Exception):
    pass


class ProviderPool:
    """Multi-provider pool with sequential failover.

    类比: RAID 1 + multipath I/O.
    Primary → fallback → last_resort.
    """

    def __init__(self, providers: list[tuple[LLMProvider, dict]] | None = None):
        self._providers: list[tuple[LLMProvider, CircuitBreaker, int]] = []
        if providers:
            for prov, config in providers:
                self.add(prov, config)

    def add(self, provider: LLMProvider, config: dict | None = None):
        cfg = config or {}
        breaker = CircuitBreaker(
            name=provider.name,
            failure_threshold=cfg.get("failure_threshold", 5),
            recovery_timeout=cfg.get("recovery_timeout", 30.0),
        )
        priority = {"primary": 0, "fallback": 1, "last_resort": 2}.get(
            cfg.get("priority", "primary"), 0
        )
        self._providers.append((provider, breaker, priority))
        self._providers.sort(key=lambda x: x[2])
        logger.info("provider_pool_add", name=provider.name, priority=priority)

    @property
    def available(self) -> bool:
        return any(b.state != "OPEN" for _, b, _ in self._providers)

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """Send prompt to first available provider. 类比: multipath I/O."""
        errors = []
        for provider, breaker, _ in self._providers:
            try:
                return await breaker.call(provider.complete, prompt, **kwargs)
            except CircuitBreakerOpenError:
                logger.info("provider_skipped", name=provider.name, reason="circuit_open")
                continue
            except Exception as e:
                errors.append((provider.name, str(e)[:200]))
                continue

        raise AllProvidersFailed(
            f"All {len(self._providers)} providers failed",
            errors=errors,
        )

    async def complete_stream(self, prompt: str, **kwargs):
        for provider, breaker, _ in self._providers:
            try:
                async for chunk in provider.complete_stream(prompt, **kwargs):
                    yield chunk
                return
            except CircuitBreakerOpenError:
                continue
            except Exception:
                continue
        raise AllProvidersFailed("All providers failed for streaming", errors=[])


class AllProvidersFailed(Exception):
    def __init__(self, message: str, errors: list = None):
        super().__init__(message)
        self.errors = errors or []
