"""Tests for capability profile and capability-aware routing."""

from agent.providers.capability import (
    MIN_SAMPLES_FOR_PROFILE,
    CapabilityProfile,
    ModelProfile,
    TaskTypeProfile,
)
from agent.providers.router import CostRouter

# ——— ModelProfile ———


class TestModelProfile:
    def test_defaults(self):
        mp = ModelProfile(model="haiku", task_type="file_edit")
        assert mp.total == 0
        assert mp.success_rate == 0.0
        assert not mp.is_significant

    def test_significance_threshold(self):
        mp = ModelProfile(model="haiku", task_type="x",
                          total=MIN_SAMPLES_FOR_PROFILE, successes=4)
        assert mp.is_significant
        assert mp.success_rate == 4 / MIN_SAMPLES_FOR_PROFILE

    def test_below_threshold_not_significant(self):
        mp = ModelProfile(model="haiku", task_type="x",
                          total=MIN_SAMPLES_FOR_PROFILE - 1, successes=3)
        assert not mp.is_significant

    def test_avg_steps(self):
        mp = ModelProfile(model="haiku", task_type="x",
                          total=3, successes=3, total_steps=9)
        assert mp.avg_steps == 3.0


# ——— TaskTypeProfile ———


class TestTaskTypeProfile:
    def test_difficulty_easy(self):
        tp = TaskTypeProfile(task_type="read", total=10, successes=10)
        assert tp.difficulty == "easy"

    def test_difficulty_moderate(self):
        tp = TaskTypeProfile(task_type="edit", total=10, successes=7)
        assert tp.difficulty == "moderate"

    def test_difficulty_hard(self):
        tp = TaskTypeProfile(task_type="migrate", total=10, successes=5)
        assert tp.difficulty == "hard"

    def test_difficulty_unknown(self):
        tp = TaskTypeProfile(task_type="new", total=3, successes=3)
        assert tp.difficulty == "unknown"


# ——— CapabilityProfile ———


class TestCapabilityProfile:
    def test_update_and_query(self):
        cp = CapabilityProfile()
        cp.update("haiku", "file_edit", "edit main.py", True, 3)
        cp.update("haiku", "file_edit", "edit config.py", True, 2)
        cp.update("haiku", "file_edit", "edit app.py", False, 5)
        cp.update("haiku", "file_edit", "edit test.py", True, 4)
        cp.update("haiku", "file_edit", "edit docs.py", True, 1)

        profile = cp.get_profile("haiku", "file_edit")
        assert profile is not None
        assert profile.total == 5
        assert profile.success_rate == 0.8
        assert profile.is_significant

    def test_best_model_selection(self):
        cp = CapabilityProfile()
        # haiku: 90% success on file_edit
        for _ in range(10):
            cp.update("haiku", "file_edit", "x", True, 1)

        # sonnet: 100% on file_edit (more expensive)
        for _ in range(5):
            cp.update("sonnet", "file_edit", "x", True, 1)

        # sonnet costs more than haiku
        cost_map = {"haiku": 1.0, "sonnet": 10.0, "opus": 50.0}

        best = cp.best_model_for("file_edit", ["haiku", "sonnet", "opus"],
                                 cost_map=cost_map)
        assert best == "haiku", (
            f"Should pick cheapest model with high success rate, got {best}"
        )

    def test_best_model_when_all_poor(self):
        cp = CapabilityProfile()
        for _ in range(5):
            cp.update("haiku", "database_migration", "x", False, 5)
        for _ in range(5):
            cp.update("sonnet", "database_migration", "x", True, 5)

        best = cp.best_model_for("database_migration", ["haiku", "sonnet"])
        assert best == "sonnet", "Should pick best available when all are poor"

    def test_cold_start_returns_none(self):
        cp = CapabilityProfile()
        best = cp.best_model_for("unknown_task", ["haiku", "sonnet"])
        assert best is None, "Insufficient data should return None (cold start)"

    def test_worst_model(self):
        cp = CapabilityProfile()
        for _ in range(5):
            cp.update("haiku", "complex", "x", False, 10)
        for _ in range(5):
            cp.update("sonnet", "complex", "x", True, 5)

        worst = cp.worst_model_for("complex")
        assert worst == "haiku"

    def test_serialization_roundtrip(self):
        cp = CapabilityProfile()
        cp.update("haiku", "file_edit", "x", True, 2)
        cp.update("sonnet", "database", "y", False, 8)

        data = cp.to_dict()
        restored = CapabilityProfile.from_dict(data)

        assert restored.get_profile("haiku", "file_edit").total == 1
        assert restored.get_profile("sonnet", "database").total == 1
        assert restored.get_task_difficulty("file_edit") == "unknown"  # < 5

    def test_stats(self):
        cp = CapabilityProfile()
        for _ in range(10):
            cp.update("haiku", "file_edit", "x", True, 1)
        stats = cp.stats()
        assert stats["total_episodes_tracked"] == 10
        assert "haiku" in stats["models_tracked"]


# ——— CostRouter with Capability ———


class TestCapabilityRouter:
    def test_router_has_capability_profile(self):
        router = CostRouter()
        assert router.capability_profile is not None

    def test_record_result_updates_profile(self):
        router = CostRouter()
        router.record_result("haiku", "file_edit", "edit x", True, 3)
        router.record_result("haiku", "file_edit", "edit y", True, 2)
        router.record_result("haiku", "file_edit", "edit z", True, 4)
        router.record_result("haiku", "file_edit", "edit w", True, 1)
        router.record_result("haiku", "file_edit", "edit v", False, 2)

        profile = router.capability_profile.get_profile("haiku", "file_edit")
        assert profile is not None
        assert profile.is_significant
        assert profile.success_rate == 0.8

    def test_cold_start_falls_back_to_cost(self):
        from unittest.mock import Mock
        router = CostRouter(strategy="ondemand")
        haiku = Mock()
        haiku.name = "haiku"
        haiku.model = "claude-haiku"
        sonnet = Mock()
        sonnet.name = "sonnet"
        sonnet.model = "claude-sonnet"
        router.register(haiku, cost_per_1m=1.0, capability=3)
        router.register(sonnet, cost_per_1m=10.0, capability=5)

        # Cold start: no capability data → falls back to cost routing
        provider = router.route_with_capability("edit main.py", task_type="file_edit")
        assert provider is not None
        # Cost routing (ondemand + simple task) → cheapest
        assert provider.name == "haiku"

    def test_stats_includes_capability(self):
        router = CostRouter()
        router.record_result("haiku", "test", "x", True, 1)
        stats = router.stats()
        assert "capability" in stats
        assert stats["capability"]["total_episodes_tracked"] == 1
