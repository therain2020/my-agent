"""Skill data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class SkillLevel(Enum):
    L1_UI = 1       # Step-by-step UI interaction instructions
    L2_API = 2      # HTTP API calls (reverse-engineered from browser traffic)
    L3_META = 3     # Pattern rewrites (meta-skills that create other skills)


@dataclass
class SkillFeedback:
    """Feedback on a skill. Written reason is MORE important than rating."""

    rating: int          # +1 (worked) or -1 (didn't work)
    reason: str          # Written reason — tells future agents what to fix
    episode_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class Skill:
    """A reusable knowledge unit accumulated across episodes."""

    id: str
    name: str
    task_type: str       # "web-automation", "file-manipulation", "data-processing"
    domain: str          # "github-login", "csv-parsing", "db-migration"
    triggers: list[str]  # Keywords that should trigger this skill
    level: SkillLevel
    approach: str        # Step-by-step instructions
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    success_rate: float = 0.0
    uses: int = 0
    created_by: str = ""      # episode_id
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_used: str = ""
    feedback: list[SkillFeedback] = field(default_factory=list)
    score: int = 0            # Sum of feedback ratings. < -3 → retired
    retired: bool = False
    merged_from: list[str] = field(default_factory=list)
    pii_checked: bool = False
    tags: list[str] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return not self.retired and self.score >= -3

    @property
    def quality_score(self) -> float:
        if self.uses == 0:
            return 0.5
        feedback_score = max(0, (self.score / max(1, len(self.feedback))) + 3) / 6
        usage_bonus = min(0.3, self.uses / 100)
        return min(1.0, feedback_score + usage_bonus)
