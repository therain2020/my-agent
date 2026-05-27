"""Correction system — structured user corrections and rule generation.

When a user points out a problem during execution, the agent:
1. Parses the correction into a structured Correction object
2. Generates a corresponding dont-do rule via LLM
3. Persists the rule to the dont-do/ directory
4. Feeds the correction back into replanning
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import structlog
import yaml

from .dont_do import Rule

logger = structlog.get_logger()


class CorrectionSource(Enum):
    USER = "user"
    AUTO_VERIFY = "auto_verify"
    RULE_ENGINE = "rule_engine"


class Severity(Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Correction:
    """A single correction record from user or system."""
    id: str
    timestamp: str
    source: CorrectionSource
    target_uri: str
    target_step: str | None = None
    issue_type: str = ""       # "wrong_action" | "wrong_object" | "wrong_plan" | "wrong_result"
    description: str = ""
    suggestion: str = ""
    severity: Severity = Severity.BLOCKER
    generated_rule_id: str | None = None
    applied: bool = False

    def to_context(self) -> dict:
        return {
            "object": self.target_uri,
            "issue": self.issue_type,
            "description": self.description,
        }


CORRECTION_TO_RULE_PROMPT = """Based on this user correction, generate a dont-do rule in YAML format.

Correction:
- Target: {target}
- Issue: {issue_type}
- Description: {description}
- Suggestion: {suggestion}

Requirements:
- id: use format "corr-{{short_hash}}"
- description: clearly state what is forbidden
- hook: choose from [PLAN, PRE_ACTION, POST_ACTION]
- match: include object and operation conditions
- action: REJECT or WARN
- message: explanation to show the user

Output ONLY valid YAML, no markdown:
```yaml
rules:
  - id: corr-xxxxx
    description: "..."
    hook: [PRE_ACTION]
    match:
      object: "..."
      operation: "..."
    action: REJECT
    message: "..."
```"""


async def correction_to_rule(correction: Correction, provider) -> Rule | None:
    """Use LLM to analyze a correction and generate a dont-do rule."""
    prompt = CORRECTION_TO_RULE_PROMPT.format(
        target=correction.target_uri,
        issue_type=correction.issue_type,
        description=correction.description,
        suggestion=correction.suggestion,
    )
    try:
        resp = await provider.complete(prompt, max_tokens=500)
        text = resp.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        data = yaml.safe_load(text)
        rule_data = data["rules"][0]
        return Rule(
            id=rule_data["id"],
            description=rule_data["description"],
            hook=rule_data["hook"],
            match=rule_data["match"],
            action=rule_data["action"],
            message=rule_data["message"],
            source=f"correction:{correction.id}",
        )
    except Exception as e:
        logger.error("correction_to_rule_failed", error=str(e))
        return None


def parse_correction_file(path: Path) -> Correction | None:
    """Parse a YAML correction file from the corrections/ directory."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Correction(
            id=data.get("id", f"corr-{uuid.uuid4().hex[:8]}"),
            timestamp=datetime.now(UTC).isoformat(),
            source=CorrectionSource.USER,
            target_uri=data["target"],
            target_step=data.get("step"),
            issue_type=data.get("issue_type", ""),
            description=data.get("description", ""),
            suggestion=data.get("suggestion", ""),
            severity=Severity(data.get("severity", "blocker")),
        )
    except Exception as e:
        logger.error("correction_parse_error", path=str(path), error=str(e))
        return None


def persist_dont_do_rule(rule: Rule, base_dir: str = "dont-do") -> Path:
    """Persist a dont-do rule to the file system, organized by object type."""
    obj_type = rule.match.get("object", "general")
    target_dir = Path(base_dir) / obj_type
    target_dir.mkdir(parents=True, exist_ok=True)

    existing = list(target_dir.glob("*.yaml"))
    if existing:
        path = existing[0]
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("rules", []).append({
            "id": rule.id,
            "description": rule.description,
            "hook": rule.hook,
            "match": rule.match,
            "action": rule.action,
            "message": rule.message,
            "source": rule.source,
        })
    else:
        path = target_dir / f"{obj_type}.yaml"
        data = {
            "rules": [{
                "id": rule.id,
                "description": rule.description,
                "hook": rule.hook,
                "match": rule.match,
                "action": rule.action,
                "message": rule.message,
                "source": rule.source,
            }],
        }

    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    logger.info("dont_do_rule_persisted", rule_id=rule.id, path=str(path))
    return path
