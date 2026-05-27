"""Claude Code SKILL.md → tool.md or role.md adapter."""

from pathlib import Path

import yaml
import structlog

from agent.tools.loader import ToolDefinition, Capability, _split_frontmatter

logger = structlog.get_logger()

# Behavioral patterns that suggest a skill should become a role, not a tool
BEHAVIORAL_KEYWORDS = [
    "writing", "coding", "reviewing", "testing", "debugging",
    "guideline", "principle", "pattern", "methodology", "tdd",
    "refactoring", "best practice", "convention", "style",
]


def convert_claude_skill(skill_path: Path) -> list[ToolDefinition]:
    """Convert a Claude Code SKILL.md to one or more ToolDefinitions.

    Returns a list because a skill can become:
    - 1 ToolDefinition (if it's a capability skill like "deploy to k8s")
    - 1 ToolDefinition marked as role (if it's behavioral like "TDD guidelines")
    """
    skill_md = skill_path / "SKILL.md" if skill_path.is_dir() else skill_path
    if not skill_md.exists():
        from agent.errors import ImportError_
        raise ImportError_(f"SKILL.md not found at {skill_md}")

    content = skill_md.read_text(encoding="utf-8")
    frontmatter_str, body = _split_frontmatter(content)
    frontmatter = yaml.safe_load(frontmatter_str) if frontmatter_str else {}

    name = frontmatter.get("name", skill_path.name if skill_path.is_dir() else skill_md.stem)
    description = frontmatter.get("description", "")
    allowed_tools = frontmatter.get("allowed-tools", [])
    triggers = frontmatter.get("triggers", [])

    is_behavioral = _classify(skill_path, description, triggers, frontmatter)

    caps = [Capability(
        name=name,
        description=description,
        parameters={},
        returns={"type": "action"},
        side_effects=["behavior_change"] if is_behavioral else ["tool_execution"],
    )]

    tool_def = ToolDefinition(
        name=name,
        version="0.1.0",
        description=description,
        objects=_infer_objects(description, triggers, allowed_tools),
        capabilities=caps,
        entry_points={},
        dependencies=allowed_tools if isinstance(allowed_tools, list) else [],
        runtime="import",
        source="claude-code-skill",
        source_command=str(skill_md),
        tool_dir=skill_md.parent if skill_md.parent != Path(".") else None,
        body=body,
    )

    if is_behavioral:
        tool_def.runtime = "import"  # Behavioral skills are prompt-only
        tool_def.source = "claude-code-skill-role"
        logger.info("skill_classified", name=name, type="role", reason="behavioral")
    else:
        logger.info("skill_classified", name=name, type="tool")

    return [tool_def]


def _classify(skill_path: Path, description: str, triggers: list, frontmatter: dict) -> bool:
    """Determine if a skill is behavioral (→ role) or capability (→ tool)."""
    text = f"{description} {' '.join(triggers)}".lower()
    return any(kw in text for kw in BEHAVIORAL_KEYWORDS)


def _infer_objects(description: str, triggers: list, tools: list) -> list[str]:
    """Infer object types from description and triggers."""
    objects = set()
    mapping = {
        "file": ["file", "code", "write", "read", "edit"],
        "git": ["git", "commit", "branch", "push", "pr", "pull request"],
        "database": ["database", "sql", "db", "migrate", "query"],
        "shell": ["bash", "shell", "command", "run", "execute", "script"],
        "test": ["test", "pytest", "unit test"],
        "deploy": ["deploy", "k8s", "kubernetes", "docker", "release"],
    }
    text = f"{description} {' '.join(triggers)} {' '.join(tools)}".lower()
    for obj, keywords in mapping.items():
        if any(kw in text for kw in keywords):
            objects.add(obj)
    return list(objects) if objects else ["general"]
