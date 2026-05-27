"""Output format rules — mandatory citation format and progressive disclosure.

Dual role:
1. Inject format constraints into the system prompt (constrain LLM output)
2. Post-hoc validation of LLM responses (detect format violations)

References follow these rules:
- Files: path/to/file:line_number
- Functions: module.function_name()
- Config: config.key.subkey

Progressive disclosure: summary → key details → full explanation (--- separated).
"""

import re
from dataclasses import dataclass, field
from enum import Enum


class DisclosureLevel(Enum):
    SUMMARY = "summary"
    KEY_DETAILS = "details"
    FULL = "full"


@dataclass
class CitationRule:
    """A single citation format rule."""
    name: str
    pattern: str
    description: str
    example: str
    required: bool = True


FILE_REFERENCE = CitationRule(
    name="file_reference",
    pattern=r"(?:[\w\-]+/)*[\w\-]+\.[a-z]{1,6}(?::\d+)?",
    description="引用文件时使用 path/to/file:line_number 格式",
    example="src/auth.py:42",
    required=True,
)

FUNCTION_REFERENCE = CitationRule(
    name="function_reference",
    pattern=r"[\w]+(?:\.[\w]+)*\(\)",
    description="引用函数时使用 module.function_name() 格式",
    example="auth.login()",
    required=False,
)

CONFIG_REFERENCE = CitationRule(
    name="config_reference",
    pattern=r"config\.[\w.]+",
    description="引用配置时使用 config.key.subkey 格式",
    example="config.database.host",
    required=False,
)


@dataclass
class OutputFormatProfile:
    """Output format configuration."""
    name: str
    citation_rules: list[CitationRule] = field(default_factory=list)
    disclosure_required: bool = True
    section_separator: str = "---"
    report_format: str = "action_report"


DEFAULT_PROFILE = OutputFormatProfile(
    name="default",
    citation_rules=[FILE_REFERENCE, FUNCTION_REFERENCE, CONFIG_REFERENCE],
    disclosure_required=True,
    section_separator="---",
    report_format="action_report",
)


class OutputFormatManager:
    """Manages output format constraints and validation.

    Phase 4: Injects format rules into prompts and validates LLM responses.
    """

    def __init__(self, profile: OutputFormatProfile | None = None):
        self.profile = profile or DEFAULT_PROFILE
        self._violations: list[dict] = []

    def get_format_prompt(self) -> str:
        """Generate format constraint text for system prompt injection."""
        rules_text = []
        for rule in self.profile.citation_rules:
            tag = "【强制】" if rule.required else "【建议】"
            rules_text.append(
                f"{tag} {rule.description}\n"
                f"  格式: {rule.pattern}\n"
                f"  示例: {rule.example}"
            )

        sep = self.profile.section_separator
        disclosure_text = ""
        if self.profile.disclosure_required:
            disclosure_text = (
                "\n## 渐进式披露要求\n\n"
                f"用 `{sep}` 分隔回答的层次：\n"
                "1. 总结层: 1-2句话概括结论\n"
                "2. 关键细节层: 核心论据或关键步骤\n"
                "3. 完整说明层: 详细展开（仅在需要时）\n"
            )

        report_text = ""
        if self.profile.report_format == "action_report":
            report_text = (
                "\n## 行动报告格式\n\n"
                "每个工具调用后，输出:\n"
                "<action_report>\n"
                "<action>执行的操作</action>\n"
                "<result>操作结果（一句话）</result>\n"
                "<evidence>验证方式</evidence>\n"
                "</action_report>\n"
            )

        return (
            "## 输出格式规范（系统级约束）\n\n"
            + "\n".join(rules_text)
            + disclosure_text
            + report_text
        )

    def validate(self, response: str) -> dict:
        """Validate LLM output against format rules."""
        self._violations = []
        issues: list[dict] = []

        for rule in self.profile.citation_rules:
            if rule.required:
                self._check_citation_compliance(response, rule, issues)

        if self.profile.disclosure_required:
            self._check_disclosure_compliance(response, issues)

        if self.profile.report_format == "action_report":
            self._check_report_compliance(response, issues)

        return {
            "valid": len([i for i in issues if i["severity"] == "error"]) == 0,
            "issues": issues,
            "warning_count": len([i for i in issues if i["severity"] == "warning"]),
            "error_count": len([i for i in issues if i["severity"] == "error"]),
        }

    def _check_citation_compliance(self, response: str, rule: CitationRule,
                                     issues: list):
        """Check for loose file references without proper citation format."""
        loose = re.compile(
            r'(?<![`"\'\w/\\])'
            r'([\w\-]+\.(?:py|js|ts|go|rs|java|yaml|json|toml|md|sql|html|css))\b'
            r'(?![\d:])'
        )
        matches = loose.findall(response)
        if matches:
            violations = list(set(matches))[:5]
            issues.append({
                "severity": "warning",
                "type": "citation_format",
                "message": (
                    f"引用了文件 {violations} 但未使用规范 `file:line` 格式 "
                    f"（如 {rule.example}）"
                ),
            })

    def _check_disclosure_compliance(self, response: str, issues: list):
        """Check if long responses use progressive disclosure separator."""
        sep = self.profile.section_separator
        if len(response) > 500 and sep not in response:
            issues.append({
                "severity": "warning",
                "type": "disclosure",
                "message": (
                    f"回答超过 500 字符但未使用 `{sep}` 分隔，"
                    f"不符合渐进式披露要求"
                ),
            })

    def _check_report_compliance(self, response: str, issues: list):
        """Check that tool calls have corresponding action reports."""
        call_count = response.count("<function_call>")
        report_count = response.count("<action_report>")
        if call_count > report_count:
            issues.append({
                "severity": "warning",
                "type": "report_format",
                "message": (
                    f"有 {call_count} 个工具调用但只有 {report_count} 个"
                    f" <action_report>，每个工具调用必须附带行动报告"
                ),
            })

    @property
    def violations(self) -> list[dict]:
        return self._violations
