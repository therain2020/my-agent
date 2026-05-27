"""Tests for cost-aware provider routing."""

from agent.providers.router import CostRouter


class FakeProvider:
    def __init__(self, name: str, model: str = "fake"):
        self._name = name
        self._model = model

    @property
    def name(self):
        return self._name

    @property
    def model(self):
        return self._model

    async def complete(self, prompt, **kwargs):
        pass


class TestCostRouter:
    def test_performance_strategy_uses_strongest(self):
        router = CostRouter(strategy="performance")
        router.register(FakeProvider("haiku"), cost_per_1m=1, capability=2)
        router.register(FakeProvider("opus"), cost_per_1m=15, capability=5)
        result = router.route("any task")
        assert result.name == "opus"

    def test_powersave_strategy_uses_cheapest(self):
        router = CostRouter(strategy="powersave")
        router.register(FakeProvider("haiku"), cost_per_1m=1, capability=2)
        router.register(FakeProvider("opus"), cost_per_1m=15, capability=5)
        result = router.route("any task")
        assert result.name == "haiku"

    def test_ondemand_complex_task_uses_strongest(self):
        router = CostRouter(strategy="ondemand")
        router.register(FakeProvider("haiku"), cost_per_1m=1, capability=2)
        router.register(FakeProvider("opus"), cost_per_1m=15, capability=5)
        result = router.route("refactor the authentication module")
        assert result.name == "opus"

    def test_ondemand_simple_task_uses_cheapest(self):
        router = CostRouter(strategy="ondemand")
        router.register(FakeProvider("haiku"), cost_per_1m=1, capability=2)
        router.register(FakeProvider("opus"), cost_per_1m=15, capability=5)
        result = router.route("what is the capital of France")
        assert result.name == "haiku"

    def test_escalate_moves_up(self):
        router = CostRouter(strategy="ondemand")
        haiku = FakeProvider("haiku")
        opus = FakeProvider("opus")
        router.register(haiku, cost_per_1m=1, capability=2)
        router.register(opus, cost_per_1m=15, capability=5)

        next_prov = router.escalate(haiku, "failed twice")
        assert next_prov is not None
        assert next_prov.name == "opus"

    def test_escalate_at_top_returns_none(self):
        router = CostRouter(strategy="ondemand")
        opus = FakeProvider("opus")
        router.register(opus, cost_per_1m=15, capability=5)

        result = router.escalate(opus, "still failing")
        assert result is None

    def test_estimated_cost(self):
        router = CostRouter()
        router.register(FakeProvider("haiku"), cost_per_1m=1, capability=2)
        cost = router.estimated_cost(5000, router._cheapest())
        assert 0.004 < cost < 0.006  # 5000/1M * $1
