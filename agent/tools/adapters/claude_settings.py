"""Claude Code settings.json → role + dont-do + probes adapter."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger()


@dataclass
class SettingsConversion:
    """Result of converting settings.json."""
    capabilities: list[str] = field(default_factory=list)
    dont_do_rules: list[dict] = field(default_factory=list)
    probes: list[dict] = field(default_factory=list)


HOOK_MAPPING = {
    "PreToolUse": "agent.tool.pre_execute",
    "PostToolUse": "agent.tool.post_execute",
    "Notification": "agent.session.event",
    "Stop": "agent.session.stop",
    "PreCompact": "agent.context.pre_compact",
}


def convert_claude_settings(settings_path: Path) -> SettingsConversion:
    """Convert Claude Code settings.json to capabilities, dont-do rules, and probes.

    permissions.allow  → capabilities
    permissions.deny   → dont-do rules
    hooks              → probe registrations
    """
    if not settings_path.exists():
        from agent.errors import ImportError_
        raise ImportError_(f"settings.json not found: {settings_path}")

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        from agent.errors import ImportError_
        raise ImportError_(f"Invalid JSON in {settings_path}: {e}")

    result = SettingsConversion()

    # permissions.allow → capabilities
    permissions = settings.get("permissions", {})
    for rule in permissions.get("allow", []):
        cap = _parse_allow_rule(rule)
        if cap:
            result.capabilities.append(cap)

    # permissions.deny → dont-do rules
    for rule in permissions.get("deny", []):
        dont_do = _parse_deny_rule(rule)
        if dont_do:
            result.dont_do_rules.append(dont_do)

    # hooks → probes
    hooks = settings.get("hooks", {})
    for event_name, hook_list in hooks.items():
        probe_point = HOOK_MAPPING.get(event_name, f"agent.{event_name.lower()}")
        for hook in hook_list:
            result.probes.append({
                "point": probe_point,
                "matcher": hook.get("matcher", "*"),
                "command": hook.get("command", ""),
                "source": "claude-code-settings",
            })

    logger.info("settings_converted",
                 capabilities=len(result.capabilities),
                 dont_do_rules=len(result.dont_do_rules),
                 probes=len(result.probes))
    return result


def _parse_allow_rule(rule: str) -> str | None:
    """Parse a Claude Code permission allow rule.

    Examples:
        "Bash(git:*)" → "CAP_SHELL_EXEC:git"
        "Read(/project/*)" → "CAP_FILE_READ:/project/*"
        "Write(/project/src/*)" → "CAP_FILE_WRITE:/project/src/*"
        "Edit(*)" → "CAP_FILE_WRITE:*"
    """
    if "(" not in rule:
        return rule
    tool, path = rule.split("(", 1)
    path = path.rstrip(")")
    mapping = {
        "Bash": "CAP_SHELL_EXEC",
        "Read": "CAP_FILE_READ",
        "Write": "CAP_FILE_WRITE",
        "Edit": "CAP_FILE_WRITE",
        "Delete": "CAP_FILE_DELETE",
    }
    for prefix, cap in mapping.items():
        if tool.startswith(prefix):
            return f"{cap}:{path}" if path != "*" else cap
    return rule


def _parse_deny_rule(rule: str) -> dict | None:
    """Parse a Claude Code permission deny rule to a dont-do rule.

    Examples:
        "Bash(rm:*)" → {'object': 'shell', 'pattern': 'rm', ...}
        "Write(/etc/*)" → {'object': 'file', 'path': '/etc/*', ...}
    """
    if "(" not in rule:
        return {"object": "general", "pattern": rule, "action": "REJECT",
                "source": "claude-code-settings"}

    tool, path = rule.split("(", 1)
    path = path.rstrip(")")

    mapping = {
        "Bash": "shell",
        "Read": "file",
        "Write": "file",
        "Edit": "file",
        "Delete": "file",
    }

    for prefix, obj in mapping.items():
        if tool.startswith(prefix):
            return {
                "object": obj,
                "pattern": path,
                "tool_prefix": tool,
                "action": "REJECT",
                "source": "claude-code-settings",
            }

    return {"object": "general", "pattern": rule, "action": "REJECT",
            "source": "claude-code-settings"}
