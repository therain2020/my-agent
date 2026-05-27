"""Tests for external adapters."""

import tempfile
from pathlib import Path

from agent.tools.loader import generate_tool_md


class TestClaudeSkillAdapter:
    def test_convert_behavioral_skill(self):
        from agent.tools.adapters.claude_skill import convert_claude_skill

        skill_content = """---
name: tdd-guidelines
description: Guidelines for test-driven development
allowed-tools: [Read, Write]
triggers: [testing, writing, coding]
---

# TDD Guidelines

Write tests first, then implement.
"""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "tdd-guidelines"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

            results = convert_claude_skill(skill_dir)
            assert len(results) == 1
            td = results[0]
            assert td.name == "tdd-guidelines"
            assert "claude-code-skill-role" in td.source  # behavioral → role
            assert "Write tests first" in td.body

    def test_convert_capability_skill(self):
        from agent.tools.adapters.claude_skill import convert_claude_skill

        skill_content = """---
name: deploy-k8s
description: Deploy application to Kubernetes cluster
allowed-tools: [Bash, Write]
triggers: [deploy, kubernetes, k8s]
---

# K8s Deploy

This skill handles k8s deployment.
"""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "deploy-k8s"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

            results = convert_claude_skill(skill_dir)
            assert len(results) == 1
            td = results[0]
            assert "deploy" in td.objects  # inferred from description


class TestMCPAdapter:
    def test_detect_transport(self):
        from agent.tools.adapters.mcp import detect_transport

        assert detect_transport("npx @anthropic/mcp-server-git") == "stdio"
        assert detect_transport("http://localhost:8080/sse") == "sse"
        assert detect_transport("https://api.example.com/mcp") == "sse"

    def test_generate_mcp_tool_def(self):
        from agent.tools.adapters.mcp import generate_mcp_tool_def
        from agent.tools.loader import Capability

        caps = [
            Capability(name="git_status", description="Show git status"),
            Capability(name="git_commit", description="Create a commit"),
        ]
        td = generate_mcp_tool_def(
            server_name="git-server",
            source="npx @anthropic/mcp-server-git",
            capabilities=caps,
            server_description="Git operations via MCP",
        )
        assert td.name == "git-server"
        assert td.runtime == "mcp"
        assert td.source == "mcp-server"
        assert td.mcp_transport == "stdio"
        assert "git" in td.objects
        assert len(td.capabilities) == 2

    def test_convert_mcp_command(self):
        from agent.tools.adapters.mcp import convert_mcp_command

        assert convert_mcp_command("mcp://npx server") == "npx server"
        assert convert_mcp_command("mcp:npx server") == "npx server"
        assert convert_mcp_command("  npx server  ") == "npx server"


class TestValidator:
    def test_validate_import_ok(self):
        from agent.tools.adapters.validator import validate_import
        from agent.tools.loader import ToolDefinition, Capability

        td = ToolDefinition(
            name="safe-tool", objects=["file"],
            capabilities=[Capability(name="read", danger_level="low")],
            runtime="import", source="builtin",
        )
        result = validate_import(td)
        assert result.passed

    def test_validate_name_conflict(self):
        from agent.tools.adapters.validator import validate_import
        from agent.tools.loader import ToolDefinition, Capability

        td = ToolDefinition(name="conflict", objects=[],
                            capabilities=[Capability(name="x")])
        result = validate_import(td, existing_names=["conflict"])
        assert any("already exists" in c.message for c in result.warnings)

    def test_validate_mcp_no_command(self):
        from agent.tools.adapters.validator import validate_import
        from agent.tools.loader import ToolDefinition, Capability

        td = ToolDefinition(
            name="bad-mcp", objects=[],
            capabilities=[Capability(name="x")],
            runtime="mcp", source_command="",  # missing command
        )
        result = validate_import(td)
        assert not result.passed
        assert any("no source_command" in e.message.lower() for e in result.errors)

    def test_validate_dangerous_capability(self):
        from agent.tools.adapters.validator import validate_import
        from agent.tools.loader import ToolDefinition, Capability

        td = ToolDefinition(
            name="risky", objects=["database"],
            capabilities=[Capability(name="drop", danger_level="critical")],
        )
        result = validate_import(td)
        assert any("critical" in c.message.lower() for c in result.confirmations)


class TestClaudeSettingsAdapter:
    def test_parse_deny_rule(self):
        from agent.tools.adapters.claude_settings import _parse_deny_rule

        result = _parse_deny_rule("Bash(rm:*)")
        assert result["object"] == "shell"
        assert result["pattern"] == "rm:*"
        assert result["action"] == "REJECT"

        result2 = _parse_deny_rule("Write(/etc/*)")
        assert result2["object"] == "file"
        assert result2["pattern"] == "/etc/*"
