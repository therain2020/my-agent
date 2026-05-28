"""Cost-aware provider routing. 类比: ondemand cpufreq governor.

Strategies: performance, powersave, ondemand.
Progressive escalation: haiku→sonnet→opus, escalate on failure.
Phase 3: Capability-aware routing overlaid on cost routing.
"""

import structlog

from agent.providers import LLMProvider
from agent.providers.capability import CapabilityProfile

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
        self.capability_profile = CapabilityProfile()

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

    def route_with_capability(self, task: str, task_type: str = "") -> LLMProvider:
        """Route with capability profile awareness.

        If we have enough data for this task_type, use capability-based
        routing to pick the cheapest model with high success rate.
        Otherwise, fall back to cost-based routing (cold start).

        Args:
            task: The task description text.
            task_type: Optional task type hint (e.g., "file_edit", "database_query").

        Returns:
            Selected LLM provider.
        """
        if not self._providers:
            raise ValueError("No providers registered in CostRouter")

        if self.strategy in ("performance", "powersave"):
            return self.route(task)

        # Try capability-based routing
        if task_type:
            model_names = [p.name for p in self._providers]
            best = self.capability_profile.best_model_for(
                task_type, model_names,
                cost_map=self._costs,
            )
            if best:
                for p in self._providers:
                    if p.name == best:
                        logger.info("capability_route", task_type=task_type,
                                    model=best)
                        return p

        # Cold start: fall back to cost-based routing
        return self.route(task)

    def record_result(self, model: str, task_type: str, task_summary: str,
                      success: bool, steps: int) -> None:
        """Record a completed task result for capability learning."""
        self.capability_profile.update(
            model, task_type, task_summary, success, steps,
        )

    def stats(self) -> dict:
        base = {
            "strategy": self.strategy,
            "providers": len(self._providers),
            "escalations": dict(self._escalation_counts),
        }
        base["capability"] = self.capability_profile.stats()
        return base

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
