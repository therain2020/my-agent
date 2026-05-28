"""Skill lifecycle management: rating, retirement, merging."""

from __future__ import annotations

import structlog

from .models import Skill, SkillFeedback
from .repository import SkillRepository

logger = structlog.get_logger()


class SkillLifecycle:
    """Manages skill lifecycle: create → consume → rate → iterate → retire → merge."""

    def __init__(self, repository: SkillRepository):
        self.repo = repository

    def record_feedback(
        self, skill_id: str, rating: int, reason: str, episode_id: str,
    ) -> Skill | None:
        """Record feedback on a skill.

        Written reason is MORE important than rating — it tells future
        agents exactly what to fix.
        """
        skill = self.repo.get(skill_id)
        if not skill:
            return None

        fb = SkillFeedback(
            rating=rating, reason=reason, episode_id=episode_id,
        )
        skill.feedback.append(fb)
        skill.score += rating
        skill.uses += 1
        total_fb = len(skill.feedback)
        positive = sum(1 for f in skill.feedback if f.rating > 0)
        skill.success_rate = positive / total_fb if total_fb else 0.0

        # Auto-retirement: score below -3
        if skill.score < -3 and not skill.retired:
            logger.warning(
                "skill_auto_retired",
                skill_id=skill_id,
                score=skill.score,
                reason="Score below -3 threshold",
            )
            skill.retired = True

        # Persist feedback
        self.repo.conn.execute(
            "INSERT INTO skill_feedback (skill_id, rating, reason, episode_id, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (skill_id, rating, reason, episode_id, fb.timestamp),
        )
        self.repo.conn.commit()
        self.repo.save(skill)

        return skill

    def merge_duplicates(self, skill_id: str) -> Skill | None:
        """Find and merge near-duplicate skills.

        Keeps the highest-quality version and absorbs the other's feedback.
        """
        skill = self.repo.get(skill_id)
        if not skill:
            return None

        duplicates = self.repo.find_near_duplicates(skill)
        if not duplicates:
            return None

        best = max([skill] + duplicates, key=lambda s: s.quality_score)

        for dup in duplicates:
            if dup.id == best.id:
                continue
            for fb in self.repo.get_feedback(dup.id):
                if fb not in best.feedback:
                    best.feedback.append(fb)
            best.score += dup.score
            best.merged_from.append(dup.id)
            best.triggers = list(set(best.triggers + dup.triggers))
            self.repo.retire(dup.id)
            logger.info("skill_merged", kept=best.id, retired=dup.id)

        self.repo.save(best)
        return best
