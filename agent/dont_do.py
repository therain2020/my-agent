"""Dont-Do rule engine. 类比: iptables netfilter.

Hook points: PLAN, PRE_ACTION, POST_ACTION.
First-match semantics. Actions: REJECT, WARN, LOG.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()


class HookPoint(Enum):
    PLAN = "plan"
    PRE_ACTION = "pre_action"
    POST_ACTION = "post_action"


class Verdict(Enum):
    ALLOW = "allow"
    REJECT = "reject"
    WARN = "warn"
    LOG = "log"


@dataclass
class Rule:
    id: str
    description: str
    hook: list[str]
    match: dict
    action: str
    message: str
    source: str = ""
    hit_count: int = 0


class DontDoEngine:
    """iptables-style rule engine with hook points.

    Phase 2: Replaces prompt injection with real runtime enforcement.
    Phase 1 prompt injection remains as Layer 1 defense.
    """

    def __init__(self):
        self._chains: dict[HookPoint, list[Rule]] = {h: [] for h in HookPoint}

    def load_rules(self, rule_paths: list[str]) -> int:
        """Load rule files from directories. Returns count of loaded rules."""
        count = 0
        for rp in rule_paths:
            path = Path(rp)
            if not path.exists():
                continue
            for yaml_file in sorted(path.glob("*.yaml")):
                try:
                    data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                    for rule_data in data.get("rules", []):
                        rule = Rule(
                            id=rule_data.get("id", f"auto-{count}"),
                            description=rule_data.get("description", ""),
                            hook=rule_data.get("hook", ["PLAN", "PRE_ACTION"]),
                            match=rule_data.get("match", {}),
                            action=rule_data.get("action", "REJECT"),
                            message=rule_data.get("message", ""),
                            source=rule_data.get("source", str(yaml_file)),
                        )
                        for hook_name in rule.hook:
                            try:
                                hook = HookPoint(hook_name.lower())
                                self._chains[hook].append(rule)
                            except ValueError:
                                logger.warning("invalid_hook", hook=hook_name, rule=rule.id)
                        count += 1
                except Exception as e:
                    logger.error("rule_load_error", file=str(yaml_file), error=str(e))
        logger.info("dont_do_loaded", rules=count)
        return count

    def check(self, hook: HookPoint, context: dict) -> tuple[Verdict, str]:
        """Check action at a hook point. First-match wins.

        context = {"object": "database", "operation": "DELETE",
                   "env": "production", "tool": "database.query"}

        Returns (verdict, message).
        """
        for rule in self._chains[hook]:
            if self._matches(rule.match, context):
                rule.hit_count += 1
                try:
                    verdict = Verdict(rule.action.lower())
                except ValueError:
                    verdict = Verdict.REJECT
                if verdict == Verdict.LOG:
                    self._audit(rule, context, hook)
                    continue
                msg = rule.message
                for key, val in context.items():
                    msg = msg.replace(f"{{{key}}}", str(val))
                return verdict, msg
        return Verdict.ALLOW, ""

    def add_rule(self, rule: Rule):
        """Programmatically add a rule."""
        for hook_name in rule.hook:
            try:
                hook = HookPoint(hook_name.lower())
                self._chains[hook].append(rule)
            except ValueError:
                pass

    def list_rules(self, hook: HookPoint | None = None) -> list[Rule]:
        """List all rules, optionally filtered by hook."""
        if hook:
            return self._chains[hook]
        all_rules = []
        for chain in self._chains.values():
            all_rules.extend(chain)
        return all_rules

    def clear(self, hook: HookPoint | None = None):
        """Clear rules."""
        if hook:
            self._chains[hook].clear()
        else:
            for chain in self._chains.values():
                chain.clear()

    def _matches(self, match: dict, context: dict) -> bool:
        """Check if context matches all conditions in a rule."""
        for key, expected in match.items():
            actual = context.get(key)

            # List match: actual must be in the list
            if isinstance(expected, list):
                if actual not in expected:
                    return False

            # Bool match: actual must be truthy
            elif expected is True:
                if not actual:
                    return False

            # Comparison: key ending with _gt, _lt, _gte, _lte
            elif key.endswith("_gt") and isinstance(expected, (int, float)):
                base_key = key[:-3]
                if not (isinstance(context.get(base_key), (int, float))
                        and context[base_key] > expected):
                    return False
            elif key.endswith("_lt") and isinstance(expected, (int, float)):
                base_key = key[:-3]
                if not (isinstance(context.get(base_key), (int, float))
                        and context[base_key] < expected):
                    return False

            # Exact match
            elif actual != expected:
                return False

        return True

    def _audit(self, rule: Rule, context: dict, hook: HookPoint):
        """Audit log for LOG rules."""
        logger.info("dont_do_audit", rule=rule.id, hook=hook.value,
                     context_summary=str(context)[:200])
