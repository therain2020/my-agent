"""PII gating for skills.

Prevents sensitive data from being saved in shared skills.
Two layers: rule-based patterns + optional LLM double-check.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger()

# Rule-based PII patterns
PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[\w\.-]+@[\w\.-]+\.\w+"), "email"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"), "bearer_token"),
    (re.compile(r"sk-[A-Za-z0-9]{32,}"), "api_key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws_access_key"),
    (re.compile(
        r"[\da-fA-F]{8}-[\da-fA-F]{4}-[\da-fA-F]{4}-[\da-fA-F]{4}-[\da-fA-F]{12}"
    ), "uuid_potential_session"),
    (re.compile(
        r"(?:password|passwd|pwd|secret|token|key)\s*[:=]\s*\S+", re.IGNORECASE
    ), "credential_assignment"),
    (re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"), "private_key"),
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "ip_address"),
]


class PIIGate:
    """Two-layer PII detection: rule-based + optional LLM double-check."""

    def __init__(self, llm_provider: Any = None):
        self.provider = llm_provider

    def check_rules(self, text: str) -> list[dict]:
        """Rule-based PII scan. Returns list of findings."""
        findings = []
        for pattern, pii_type in PII_PATTERNS:
            matches = pattern.findall(text)
            for match in matches:
                findings.append({
                    "type": pii_type,
                    "match": str(match)[:50],
                    "method": "rule",
                })
        return findings

    async def check_llm(self, text: str) -> list[dict]:
        """LLM-based PII scan for semantic detection."""
        if not self.provider:
            return []

        prompt = (
            "Scan for PII: emails, API keys, tokens, passwords, names, "
            "phone numbers, addresses, session IDs, internal URLs with credentials.\n"
            'Respond JSON: [{"type": "email|token|password|...", '
            '"description": "what was found (redacted)"}]\n'
            "If nothing, respond [].\n\n"
            f"Text:\n{text[:2000]}"
        )
        try:
            resp = await self.provider.complete(prompt, max_tokens=200)
            import json
            return json.loads(resp.content.strip())
        except Exception as e:
            logger.error("pii_llm_check_failed", error=str(e))
            return []

    async def validate(self, skill_name: str, content: str) -> tuple[bool, list[dict]]:
        """Validate skill content for PII. Returns (clean, findings)."""
        all_findings = self.check_rules(content)

        if self.provider:
            llm_findings = await self.check_llm(content)
            all_findings.extend(llm_findings)

        if all_findings:
            logger.warning(
                "pii_detected_in_skill",
                skill=skill_name,
                finding_count=len(all_findings),
                types=[f["type"] for f in all_findings],
            )
            return False, all_findings

        return True, []
