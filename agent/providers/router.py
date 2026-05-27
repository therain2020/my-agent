"""Cost-aware provider routing. 类比: ondemand cpufreq governor.

Strategies: performance, powersave, ondemand.
Progressive escalation: haiku→sonnet→opus, escalate on failure.
"""

import structlog

from agent.providers import LLMProvider

logger = structlog.get_logger()

KNOWN_COMPLEX = [
    "refactor", "migrate", "redesign", "architect", "rewrite",
    "restructure", "overhaul", "upgrade",
]
KNOWN_SIMPLE = [
    "fix typo", "spelling", "read", "show", "list", "what is",
    "explain", "summarize", "format",
]


class CostRouter:
    """Routes tasks to providers based on cost and complexity.

    类比: Linux ondemand cpufreq governor.
    Starts cheap, escalates on failure.
    """

    def __init__(self, strategy: str = "ondemand"):
        self.strategy = strategy
        self._providers: list[LLMProvider] = []
        self._costs: dict[str, float] = {}       # provider_name → $/1M tokens
        self._capabilities: dict[str, int] = {}  # provider_name → 1-5
        self._escalation_counts: dict[str, int] = {}

    def register(self, provider: LLMProvider, cost_per_1m: float = 0.0,
                 capability: int = 3):
        """Register a provider with cost and capability metadata."""
        self._providers.append(provider)
        self._costs[provider.name] = cost_per_1m
        self._capabilities[provider.name] = capability
        self._providers.sort(key=lambda p: self._capabilities[p.name])

    @property
    def providers(self) -> list[LLMProvider]:
        return list(self._providers)

    def route(self, task: str) -> LLMProvider:
        """Select provider for a new task.

        performance → always strongest
        powersave  → always cheapest
        ondemand   → starts cheap, escalates on failure
        """
        if not self._providers:
            raise ValueError("No providers registered in CostRouter")

        if self.strategy == "performance":
            return self._strongest()

        if self.strategy == "powersave":
            return self._cheapest()

        # ondemand: start cheap but skip the cheap model for known-complex tasks
        task_lower = task.lower()
        if any(kw in task_lower for kw in KNOWN_COMPLEX):
            return self._strongest()
        if any(kw in task_lower for kw in KNOWN_SIMPLE):
            return self._cheapest()

        return self._cheapest()

    def escalate(self, current: LLMProvider, reason: str = "") -> LLMProvider | None:
        """Escalate to the next-stronger provider. 类比: CPU freq upscale.

        Returns None if already at strongest.
        """
        idx = self._index_of(current)
        if idx < len(self._providers) - 1:
            next_prov = self._providers[idx + 1]
            key = current.name
            self._escalation_counts[key] = self._escalation_counts.get(key, 0) + 1
            logger.info("provider_escalate",
                        from_provider=current.name,
                        to_provider=next_prov.name,
                        reason=reason)
            return next_prov
        return None

    def stats(self) -> dict:
        return {
            "strategy": self.strategy,
            "providers": len(self._providers),
            "escalations": dict(self._escalation_counts),
        }

    def estimated_cost(self, tokens: int, provider: LLMProvider) -> float:
        """Estimate cost for a given token count."""
        cost_per_1m = self._costs.get(provider.name, 0)
        return tokens / 1_000_000 * cost_per_1m

    def _cheapest(self) -> LLMProvider:
        return self._providers[0]

    def _strongest(self) -> LLMProvider:
        return self._providers[-1]

    def _index_of(self, provider: LLMProvider) -> int:
        for i, p in enumerate(self._providers):
            if p.name == provider.name:
                return i
        return 0
