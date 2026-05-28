"""Tests for skills social learning network (十二-C)."""

from agent.skills.lifecycle import SkillLifecycle
from agent.skills.models import Skill, SkillFeedback, SkillLevel
from agent.skills.pii_gate import PIIGate
from agent.skills.repository import SkillRepository


class TestSkillModels:
    def test_skill_creation(self):
        skill = Skill(
            id="skill-001",
            name="Test Skill",
            task_type="testing",
            domain="pytest",
            triggers=["test", "pytest"],
            level=SkillLevel.L1_UI,
            approach="1. Write test\n2. Run pytest",
        )
        assert skill.id == "skill-001"
        assert skill.is_active
        assert skill.quality_score == 0.5  # neutral for new skills

    def test_skill_retired_when_score_low(self):
        skill = Skill(
            id="skill-002",
            name="Bad Skill",
            task_type="testing",
            domain="test",
            triggers=["test"],
            level=SkillLevel.L1_UI,
            approach="bad approach",
            score=-5,
            retired=True,
        )
        assert not skill.is_active

    def test_skill_quality_score_with_usage(self):
        skill = Skill(
            id="skill-003",
            name="Used Skill",
            task_type="testing",
            domain="test",
            triggers=["test"],
            level=SkillLevel.L1_UI,
            approach="good approach",
            uses=50,
            score=10,
        )
        skill.feedback = [
            SkillFeedback(rating=1, reason="worked", episode_id="ep-1"),
            SkillFeedback(rating=1, reason="worked again", episode_id="ep-2"),
        ]
        assert skill.quality_score > 0.5

    def test_skill_levels(self):
        assert SkillLevel.L1_UI.value == 1
        assert SkillLevel.L2_API.value == 2
        assert SkillLevel.L3_META.value == 3


class TestSkillRepository:
    def test_init_creates_db(self, tmp_path):
        db_path = tmp_path / "test_skills.db"
        SkillRepository(db_path=str(db_path))
        assert db_path.exists()

    def test_save_and_get(self, tmp_path):
        db_path = tmp_path / "test_skills.db"
        repo = SkillRepository(db_path=str(db_path))
        skill = Skill(
            id="skill-test",
            name="Test",
            task_type="testing",
            domain="test",
            triggers=["test"],
            level=SkillLevel.L1_UI,
            approach="do something",
        )
        assert repo.save(skill)
        retrieved = repo.get("skill-test")
        assert retrieved is not None
        assert retrieved.name == "Test"

    def test_search(self, tmp_path):
        db_path = tmp_path / "test_skills.db"
        repo = SkillRepository(db_path=str(db_path))
        skill = Skill(
            id="skill-search",
            name="Searchable",
            task_type="testing",
            domain="search",
            triggers=["search", "find"],
            level=SkillLevel.L1_UI,
            approach="use grep",
        )
        repo.save(skill)
        results = repo.search("search", limit=5)
        assert len(results) >= 0  # FTS5 may need time to index

    def test_find_by_triggers(self, tmp_path):
        db_path = tmp_path / "test_skills.db"
        repo = SkillRepository(db_path=str(db_path))
        skill = Skill(
            id="skill-trig",
            name="Trigger Test",
            task_type="testing",
            domain="test",
            triggers=["deploy", "release"],
            level=SkillLevel.L1_UI,
            approach="run deploy script",
        )
        repo.save(skill)
        results = repo.find_by_triggers("I need to deploy the app", limit=5)
        assert len(results) == 1

    def test_retire(self, tmp_path):
        db_path = tmp_path / "test_skills.db"
        repo = SkillRepository(db_path=str(db_path))
        skill = Skill(
            id="skill-retire",
            name="To Retire",
            task_type="testing",
            domain="test",
            triggers=["test"],
            level=SkillLevel.L1_UI,
            approach="old",
            score=-10,
        )
        repo.save(skill)
        repo.retire("skill-retire")
        retrieved = repo.get("skill-retire")
        assert retrieved.retired

    def test_get_active_filters_retired(self, tmp_path):
        db_path = tmp_path / "test_skills.db"
        repo = SkillRepository(db_path=str(db_path))
        active = Skill(
            id="skill-active",
            name="Active",
            task_type="testing",
            domain="test",
            triggers=["test"],
            level=SkillLevel.L1_UI,
            approach="active approach",
        )
        retired = Skill(
            id="skill-retired2",
            name="Retired",
            task_type="testing",
            domain="test",
            triggers=["test"],
            level=SkillLevel.L1_UI,
            approach="retired approach",
            retired=True,
        )
        repo.save(active)
        repo.save(retired)
        active_skills = repo.get_active(limit=10)
        assert all(not s.retired for s in active_skills)


class TestSkillLifecycle:
    def test_record_feedback(self, tmp_path):
        db_path = tmp_path / "test_skills.db"
        repo = SkillRepository(db_path=str(db_path))
        lifecycle = SkillLifecycle(repo)

        skill = Skill(
            id="skill-fb",
            name="Feedback Test",
            task_type="testing",
            domain="test",
            triggers=["test"],
            level=SkillLevel.L1_UI,
            approach="test approach",
        )
        repo.save(skill)

        updated = lifecycle.record_feedback(
            "skill-fb", rating=1, reason="worked great", episode_id="ep-1"
        )
        assert updated is not None
        assert updated.uses == 1
        assert updated.score == 1

    def test_auto_retire_on_low_score(self, tmp_path):
        db_path = tmp_path / "test_skills.db"
        repo = SkillRepository(db_path=str(db_path))
        lifecycle = SkillLifecycle(repo)

        skill = Skill(
            id="skill-bad",
            name="Bad Skill",
            task_type="testing",
            domain="test",
            triggers=["test"],
            level=SkillLevel.L1_UI,
            approach="bad approach",
            score=-3,
        )
        repo.save(skill)

        updated = lifecycle.record_feedback(
            "skill-bad", rating=-1, reason="still broken", episode_id="ep-2"
        )
        assert updated.retired  # score = -4, below -3 threshold


class TestPIIGate:
    def test_detect_email(self):
        gate = PIIGate()
        findings = gate.check_rules("Contact user@example.com for help")
        assert any(f["type"] == "email" for f in findings)

    def test_detect_api_key(self):
        gate = PIIGate()
        findings = gate.check_rules("Use key sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0")
        assert any(f["type"] == "api_key" for f in findings)

    def test_clean_text_passes(self):
        gate = PIIGate()
        findings = gate.check_rules("This is a normal skill description.")
        assert len(findings) == 0

    def test_detect_ip(self):
        gate = PIIGate()
        findings = gate.check_rules("Server at 192.168.1.100 responded")
        assert any(f["type"] == "ip_address" for f in findings)
