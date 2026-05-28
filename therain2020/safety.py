"""Unified runtime safety engine — iptables-style hook chains.

Merges DontDoEngine (runtime hooks, first-match semantics) and
SecurityManager (restricted-path checks) into a single engine.

Rules are loaded from YAML files and can be added programmatically
(from the correction system).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from .constants import DONT_DO_HOOKS  # noqa: F401 — documented hook list


class HookPoint(Enum):
    PLAN = "PLAN"
    PRE_ACTION = "PRE_ACTION"
    POST_ACTION = "POST_ACTION"


class Verdict(Enum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"
    WARN = "WARN"
    LOG = "LOG"


@dataclass
class Rule:
    id: str
    description: str
    hooks: list[HookPoint]
    match: dict  # {"tool": "rm", "params.path": "/etc/*"}
    action: Verdict
    message: str = ""


@dataclass
class CheckResult:
    verdict: Verdict
    rule_id: str | None = None
    message: str = ""


# Restricted path prefixes (migrated from old SecurityManager)
_RESTRICTED_PREFIXES = [
    "/etc/", "/boot/", "/sys/", "/proc/", "/dev/",
    "C:\\Windows\\", "C:\\Windows\\System32\\",
    "~/.ssh/", "~/.gnupg/",
]

_SENSITIVE_FILES = [
    ".env", ".env.local", ".env.production",
    "credentials.json", "secrets.yaml", "id_rsa", "id_ed25519",
]


class SafetyEngine:
    """iptables-style rule engine with hook points and first-match semantics."""

    def __init__(self, rules_dir: Path | None = None):
        self.rules: list[Rule] = []
        self._load_builtin_rules()
        if rules_dir and rules_dir.is_dir():
            self._load_rules_from_dir(rules_dir)

    # -- rule loading -----------------------------------------------------

    def _load_builtin_rules(self):
        """Always-on restricted-path protection."""
        for prefix in _RESTRICTED_PREFIXES:
            self.rules.append(Rule(
                id=f"builtin:restrict-path:{prefix}",
                description=f"Block writes to {prefix}",
                hooks=[HookPoint.PRE_ACTION],
                match={"tool": ["write_file", "delete_file", "rm", "shutil.rmtree"],
                        "params.path_glob": prefix + "*"},
                action=Verdict.REJECT,
                message=f"Writing to {prefix} is blocked by default",
            ))
        for fname in _SENSITIVE_FILES:
            self.rules.append(Rule(
                id=f"builtin:sensitive-file:{fname}",
                description=f"Block reads of {fname}",
                hooks=[HookPoint.PRE_ACTION],
                match={"tool": "read_file", "params.path_glob": f"*/{fname}"},
                action=Verdict.WARN,
                message=f"Reading {fname} may expose credentials",
            ))

    def _load_rules_from_dir(self, dir: Path):
        for path in sorted(dir.glob("*.yaml")):
            try:
                _load_yaml_rules(self, path)
            except Exception:
                pass

    # -- core check -------------------------------------------------------

    def check(self, hook: HookPoint, context: dict) -> CheckResult:
        """Run the rule chain for `hook` against `context`.

        First-match semantics: the first rule whose match block fully
        matches `context` wins. LOG verdicts continue to the next rule.
        """
        for rule in self.rules:
            if hook not in rule.hooks:
                continue
            if not self._matches(rule.match, context):
                continue
            if rule.action == Verdict.LOG:
                continue
            return CheckResult(verdict=rule.action, rule_id=rule.id, message=rule.message)
        return CheckResult(verdict=Verdict.ALLOW)

    def add_rule(self, rule: Rule):
        """Programmatic rule addition — from the correction system."""
        self.rules.append(rule)

    # -- matching engine --------------------------------------------------

    def _matches(self, match: dict, context: dict) -> bool:
        """Check whether `match` (rule conditions) matches `context` (actual data).

        Supports:
          - exact:          {"tool": "rm"}
          - list (in):      {"tool": ["rm", "delete"]}
          - boolean:        {"params.force": True}
          - glob:           {"params.path_glob": "/etc/*"}
          - comparison:     {"params.size_gt": 1000}  (also _lt, _gte, _lte)
        """
        for key, expected in match.items():
            actual = _resolve_key(key, context)
            if actual is None:
                return False
            # list match
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            # glob match (key suffix _glob)
            elif key.endswith("_glob") and isinstance(expected, str):
                if not fnmatch.fnmatch(str(actual), expected):
                    return False
            # comparison match (key suffix _gt, _lt, _gte, _lte)
            elif key.endswith(("_gt", "_lt", "_gte", "_lte")):
                if not _compare(expected, actual, key.rsplit("_", 1)[1]):
                    return False
            # exact / bool match
            elif actual != expected:
                return False
        return True

    # -- LLM context ------------------------------------------------------

    def safety_context(self) -> str:
        """Generate safety context text for the LLM system prompt."""
        active = [r for r in self.rules if r.action == Verdict.REJECT]
        if not active:
            return ""
        lines = ["Safety rules (DO NOT violate):"]
        for r in active:
            lines.append(f"  - {r.message or r.description}")
        return "\n".join(lines)


# -- helpers --------------------------------------------------------------

def _resolve_key(dotted: str, context: dict):
    """Resolve 'params.path' to context['params']['path']."""
    parts = dotted.removesuffix("_glob").removesuffix("_gt").removesuffix(
        "_lt").removesuffix("_gte").removesuffix("_lte")
    cur = context
    for part in parts.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _compare(expected, actual, op: str) -> bool:
    try:
        a = float(actual)  # type: ignore[arg-type]
        e = float(expected)
    except (TypeError, ValueError):
        return False
    if op == "gt":
        return a > e
    if op == "lt":
        return a < e
    if op == "gte":
        return a >= e
    if op == "lte":
        return a <= e
    return False


def _load_yaml_rules(engine: SafetyEngine, path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return
    for rule_data in data.get("rules", []):
        try:
            engine.rules.append(Rule(
                id=rule_data["id"],
                description=rule_data.get("description", ""),
                hooks=[HookPoint(h) for h in rule_data["hooks"]],
                match=rule_data.get("match", {}),
                action=Verdict(rule_data.get("action", "LOG")),
                message=rule_data.get("message", ""),
            ))
        except (KeyError, ValueError):
            continue
