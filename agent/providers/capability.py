"""Capability profile — per-model, per-task-type success rate tracking.

Based on Karpathy's "Jagged Frontier" concept (llm-as-ghost-jagged-statistical.md):
LLM capability is not uniform — it's jagged. The same model can be PhD-level
in one area and kindergarten-level in another. This module tracks the shape
of that frontier empirically.

OS analogy: NUMA scheduling / CPU affinity — route tasks to the best-fit model.
"""

from dataclasses import dataclass

import structlog

logger = structlog.get_logger()

MIN_SAMPLES_FOR_PROFILE = 5  # Minimum episodes before a profile is statistically meaningful


@dataclass
class ModelProfile:
    """Success rate data for one model on one task type."""
    model: str
    task_type: str
    total: int = 0
    successes: int = 0
    total_steps: int = 0

    @property
    def success_rate(self) -> float:
        return self.successes / self.total if self.total > 0 else 0.0

    @property
    def avg_steps(self) -> float:
        return self.total_steps / self.total if self.total > 0 else 0.0

    @property
    def is_significant(self) -> bool:
        """Has enough data for statistically meaningful decisions."""
        return self.total >= MIN_SAMPLES_FOR_PROFILE


@dataclass
class TaskTypeProfile:
    """Aggregated profile across all models for one task type."""
    task_type: str
    total: int = 0
    successes: int = 0

    @property
    def success_rate(self) -> float:
        return self.successes / self.total if self.total > 0 else 0.0

    @property
    def difficulty(self) -> str:
        """Classify task type difficulty based on success rate."""
        if self.total < MIN_SAMPLES_FOR_PROFILE:
            return "unknown"
        if self.success_rate >= 0.85:
            return "easy"
        if self.success_rate >= 0.6:
            return "moderate"
        return "hard"


class CapabilityProfile:
    """Tracks model performance per task type to enable capability-aware routing.

    Data source: event_store.get_events_by_type(EventType.GOAL_COMPLETED)
    """

    def __init__(self):
        self._models: dict[str, ModelProfile] = {}   # "model:task_type" → profile
        self._task_types: dict[str, TaskTypeProfile] = {}

    # ——— Update ———

    def update(self, model: str, task_type: str, task_summary: str,
               success: bool, steps: int) -> None:
        """Record one episode result."""
        key = f"{model}:{task_type}"
        mp = self._models.get(key)
        if mp is None:
            mp = ModelProfile(model=model, task_type=task_type)
            self._models[key] = mp
        mp.total += 1
        if success:
            mp.successes += 1
        mp.total_steps += steps

        tp = self._task_types.get(task_type)
        if tp is None:
            tp = TaskTypeProfile(task_type=task_type)
            self._task_types[task_type] = tp
        tp.total += 1
        if success:
            tp.successes += 1

        logger.debug("capability_updated", model=model, task_type=task_type,
                     success=success, rate=mp.success_rate)

    def update_from_episode(self, model: str, task_type: str,
                            task_summary: str, success: bool, steps: int) -> None:
        """Alias for update — record one episode result."""
        self.update(model, task_type, task_summary, success, steps)

    # ——— Query ———

    def get_profile(self, model: str, task_type: str) -> ModelProfile | None:
        """Get the profile for a specific model+task_type combo."""
        return self._models.get(f"{model}:{task_type}")

    def get_task_difficulty(self, task_type: str) -> str:
        """Get the difficulty classification for a task type."""
        tp = self._task_types.get(task_type)
        return tp.difficulty if tp else "unknown"

    def best_model_for(self, task_type: str,
                       available_models: list[str],
                       cost_map: dict[str, float] | None = None) -> str | None:
        """Recommend the best model for a given task type.

        Strategy: Find the cheapest model with success_rate >= 85%.
        If none meet the threshold, recommend the strongest.
        If no data, return None (caller uses default strategy).

        Args:
            task_type: The type of task.
            available_models: List of available model names.
            cost_map: Optional model_name → cost mapping for tie-breaking.

        Returns:
            Recommended model name, or None if insufficient data.
        """
        candidates = []
        for model in available_models:
            profile = self.get_profile(model, task_type)
            if profile and profile.is_significant:
                candidates.append((model, profile.success_rate))

        if not candidates:
            return None  # Cold start: insufficient data

        # Prefer models above 85% success rate
        good_enough = [(m, r) for m, r in candidates if r >= 0.85]
        if good_enough and cost_map:
            return min(good_enough, key=lambda x: cost_map.get(x[0], 999))[0]
        if good_enough:
            return good_enough[0][0]

        # No model is good enough → recommend the best available
        best = max(candidates, key=lambda x: x[1])
        return best[0]

    def worst_model_for(self, task_type: str) -> str | None:
        """Find which model performs worst on this task type (for avoidance)."""
        worst = None
        worst_rate = 1.0
        for key, mp in self._models.items():
            if mp.task_type == task_type and mp.is_significant:
                if mp.success_rate < worst_rate:
                    worst_rate = mp.success_rate
                    worst = mp.model
        return worst

    # ——— Stats ———

    def stats(self) -> dict:
        """Aggregated statistics for observability."""
        model_counts = {}
        for mp in self._models.values():
            model_counts[mp.model] = model_counts.get(mp.model, 0) + mp.total

        task_difficulties = {}
        for tt, tp in self._task_types.items():
            if tp.total >= MIN_SAMPLES_FOR_PROFILE:
                task_difficulties[tt] = tp.difficulty

        return {
            "total_episodes_tracked": sum(mp.total for mp in self._models.values()),
            "models_tracked": list(model_counts.keys()),
            "model_episodes": model_counts,
            "task_difficulties": task_difficulties,
            "min_samples_for_significance": MIN_SAMPLES_FOR_PROFILE,
        }

    def to_dict(self) -> dict:
        """Serialize all profiles for persistence."""
        return {
            "models": {
                key: {
                    "model": mp.model,
                    "task_type": mp.task_type,
                    "total": mp.total,
                    "successes": mp.successes,
                    "total_steps": mp.total_steps,
                }
                for key, mp in self._models.items()
            },
            "task_types": {
                tt: {"task_type": tp.task_type, "total": tp.total,
                     "successes": tp.successes}
                for tt, tp in self._task_types.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CapabilityProfile":
        """Restore from serialized data."""
        profile = cls()
        for key, d in data.get("models", {}).items():
            profile._models[key] = ModelProfile(**d)
        for tt, d in data.get("task_types", {}).items():
            profile._task_types[tt] = TaskTypeProfile(**d)
        return profile
