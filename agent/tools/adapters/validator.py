"""Import validator. 类比: 包管理器签名验证."""

from dataclasses import dataclass, field

import structlog

from agent.tools.loader import ToolDefinition

logger = structlog.get_logger()

DANGEROUS_CAPABILITIES = [
    "CAP_DB_SCHEMA", "CAP_DB_WRITE", "CAP_DB_DELETE",
    "CAP_FILE_DELETE", "CAP_SHELL_EXEC",
    "CAP_GIT_FORCE_PUSH", "CAP_GIT_DELETE_BRANCH",
    "CAP_NET_POST", "CAP_PROCESS_KILL",
]


@dataclass
class ValidationCheck:
    level: str  # OK | WARN | CONFIRM | ERROR
    message: str


@dataclass
class ValidationResult:
    checks: list[ValidationCheck] = field(default_factory=list)
    passed: bool = True

    @property
    def warnings(self) -> list[ValidationCheck]:
        return [c for c in self.checks if c.level == "WARN"]

    @property
    def confirmations(self) -> list[ValidationCheck]:
        return [c for c in self.checks if c.level == "CONFIRM"]

    @property
    def errors(self) -> list[ValidationCheck]:
        return [c for c in self.checks if c.level == "ERROR"]


def validate_import(
    tool_def: ToolDefinition,
    existing_names: list[str] | None = None,
    granted_capabilities: list[str] | None = None,
) -> ValidationResult:
    """Validate an imported tool definition.

    Checks:
    1. Name conflicts
    2. Dangerous capabilities
    3. Capability vs granted capability mismatch
    """
    checks = []
    existing = existing_names or []

    # 1. Name conflict
    if tool_def.name in existing:
        checks.append(ValidationCheck(
            level="WARN",
            message=f"Tool '{tool_def.name}' already exists and will be overwritten"
        ))

    # 2. Dangerous capabilities
    for cap in tool_def.capabilities:
        if cap.danger_level in ("high", "critical"):
            checks.append(ValidationCheck(
                level="CONFIRM",
                message=f"'{tool_def.name}.{cap.name}' is marked {cap.danger_level} risk"
            ))

    # 3. Runtime check — MCP tools need special attention
    if tool_def.runtime == "mcp":
        if not tool_def.source_command:
            checks.append(ValidationCheck(
                level="ERROR",
                message=f"'{tool_def.name}' has runtime=mcp but no source_command"
            ))
        checks.append(ValidationCheck(
            level="WARN",
            message=f"'{tool_def.name}' runs as MCP subprocess. "
                    f"Ensure you trust the source: {tool_def.source_command}"
        ))

    # 4. Source validation
    if tool_def.source == "builtin":
        pass  # Builtin tools are trusted
    elif tool_def.source in ("claude-code-skill", "claude-code-skill-role"):
        checks.append(ValidationCheck(
            level="OK",
            message="Imported from Claude Code skill"
        ))
    elif tool_def.source == "mcp-server":
        checks.append(ValidationCheck(
            level="WARN",
            message="Imported from MCP server. "
                    "Verify the server's trustworthiness before use."
        ))

    has_errors = any(c.level == "ERROR" for c in checks)
    result = ValidationResult(checks=checks, passed=not has_errors)

    if has_errors:
        logger.warning("import_validation_failed", tool=tool_def.name,
                       errors=[c.message for c in checks if c.level == "ERROR"])
    elif result.warnings:
        logger.info("import_validation_warnings", tool=tool_def.name,
                    warnings=len(result.warnings))
    else:
        logger.info("import_validation_ok", tool=tool_def.name)

    return result
