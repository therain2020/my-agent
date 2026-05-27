"""Plain text rules → behavior_rule adapter.

Converts CLAUDE.md, Cursor rules, Aider CONVENTIONS.md → prompt behavior rules.
"""

from pathlib import Path

import structlog

logger = structlog.get_logger()


def convert_plain_text(path: Path, source_type: str = "") -> str:
    """Read a plain text rules file and return its content."""
    if not path.exists():
        from agent.errors import ImportError_
        raise ImportError_(f"File not found: {path}")

    content = path.read_text(encoding="utf-8")
    source_label = source_type or _detect_source(path)
    logger.info("plain_text_imported", path=str(path), source=source_label,
                size=len(content))
    return content


def convert_cursor_rules(rules_dir: Path) -> list[dict]:
    """Convert .cursor/rules/*.mdc to behavior rules."""
    if not rules_dir.exists():
        from agent.errors import ImportError_
        raise ImportError_(f"Cursor rules directory not found: {rules_dir}")

    rules = []
    for rule_file in sorted(rules_dir.glob("*.mdc")):
        content = rule_file.read_text(encoding="utf-8")
        rules.append({
            "name": rule_file.stem,
            "content": content,
            "source": "cursor-rules",
            "path": str(rule_file),
        })
    logger.info("cursor_rules_imported", count=len(rules))
    return rules


def _detect_source(path: Path) -> str:
    """Detect source type from filename."""
    name = path.name.lower()
    if "claude.md" in name:
        return "claude-code-claude-md"
    if "conventions" in name:
        return "aider-conventions"
    if path.suffix == ".mdc":
        return "cursor-rule"
    return "plain-text"
