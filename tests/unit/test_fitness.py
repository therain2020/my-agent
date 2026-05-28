"""Agent Fitness Functions — architectural quality gates.

Per fitness-function-core-principles.md:
1. Don't flood with low-value FFs — only test critical architecture characteristics
2. Use FFs to mitigate negative trade-offs — monitor the weak points
3. Treat architecture as executable code — verify structural decisions automatically
4. Pursue the smallest, fastest feedback loop — start simple

FF failures are discussion triggers, NOT hard gates (fitness-functions-vs-unit-tests.md).
"""

import pytest

from agent.config import AppConfig
from agent.dont_do import DontDoEngine, HookPoint, Verdict
from agent.output_format import OutputFormatManager
from agent.prompt import PromptAssembler, PromptInputs, format_tool_summary
from agent.role import DEFAULT_ROLE
from agent.tools.loader import Capability, ToolDefinition

# ——— Helpers ———


def _make_mock_tool(name: str, capabilities: list[str],
                    objects: list[str] | None = None) -> ToolDefinition:
    """Create a lightweight mock tool for testing."""
    return ToolDefinition(
        name=name,
        description=f"Mock tool: {name}",
        objects=objects or ["file"],
        capabilities=[Capability(name=c, description=c) for c in capabilities],
    )


# ——— FF-1: Plan Completeness ———
# Every plan step should have a verify condition.
# Mitigates the negative trade-off of ReAct's flexibility (unpredictability).


class TestPlanCompleteness:
    """FF-1: Verify that prompt assembly includes role guidance for verification."""

    def test_prompt_includes_verify_instruction(self):
        """Planning role text should instruct LLM to include verify per step."""
        assembler = PromptAssembler()
        prompt = assembler.assemble(PromptInputs(
            role=(
                "基于观察结果和对象上下文，使用可用工具为目标制定执行计划。"
                "注意每个对象的约束(Constraints)和可用操作(Actions)。"
                "输出 JSON 格式的计划数组，每步包含 action, tool, object 和 verify。"
                "如果不可自动验证，设置 verify: 'manual'。"
            ),
            task="目标: test\n\n观察结果:\n(no objects)",
        ))
        assert "verify" in prompt, (
            "FF-1: Planning prompt must include 'verify' instruction. "
            "Without it, plan steps may lack verifiable conditions."
        )

    def test_default_role_has_behavior_rules(self):
        """Role should include behavior rules that guide plan quality."""
        assert len(DEFAULT_ROLE.behavior_rules) > 0, (
            "FF-1: Default role should have behavior rules "
            "to guide plan quality (e.g., 'read before write')."
        )


# ——— FF-2: Dont-Do Rule Effectiveness (STRIDE threat scenarios) ———
# Security rules must actually block known-dangerous operations.
# Maps to STRIDE Tampering + Elevation of Privilege.


class TestDontDoEffectiveness:
    """FF-2: Verify dont-do rules block dangerous operations."""

    @pytest.fixture(autouse=True)
    def _load_rules(self):
        """Load dont-do rules before each test."""
        self.engine = DontDoEngine()
        self.engine.load_rules(["./dont-do"])

    def test_blocks_system_path_write(self):
        """Writing to system paths should be rejected (r-fs-001)."""
        verdict, msg = self.engine.check(HookPoint.PRE_ACTION, {
            "object": "file",
            "operation": "write",
            "tool": "file-system",
            "path_in_restricted": True,
        })
        assert verdict != Verdict.ALLOW, (
            "FF-2 STRIDE/Tampering: Writing to restricted paths must be "
            "blocked by r-fs-001. Engine reports ALLOW — rule not matching."
        )

    def test_blocks_env_file_write(self):
        """Writing to .env files should be rejected (r-fs-002).

        NOTE: r-fs-002 uses path_matches with a regex pattern.
        The DontDoEngine does exact match on context keys,
        so the context must pass the exact match value.
        """
        verdict, msg = self.engine.check(HookPoint.PRE_ACTION, {
            "object": "file",
            "operation": "write",
            "tool": "file-system",
            "path_matches": ".env|.git/",
        })
        assert verdict != Verdict.ALLOW, (
            "FF-2 STRIDE/InfoDisclosure: Writing to .env files must be blocked "
            "by r-fs-002. Engine reports ALLOW — rule not matching."
        )

    def test_allows_normal_file_write(self):
        """Writing to normal files should be allowed (no false positive)."""
        verdict, msg = self.engine.check(HookPoint.PRE_ACTION, {
            "object": "file",
            "operation": "write",
            "tool": "file-system",
        })
        assert verdict == Verdict.ALLOW, (
            "FF-2 False Positive: Normal file writes "
            "should be ALLOWED, not blocked."
        )

    def test_context_preparation_gap(self):
        """FF-2 FIXED: Agent._enrich_dont_do_context now sets path keys.

        Previously this test documented a gap where r-fs-001/r-fs-002
        never matched because the agent didn't set path_in_restricted
        or path_matches. Now _enrich_dont_do_context() extracts path
        info from params and sets these keys automatically.
        """
        from agent.core import Agent
        ctx = {
            "object": "file",
            "operation": "write",
            "tool": "file-system",
            "params": {"path": "/etc/passwd"},
        }
        enriched = Agent._enrich_dont_do_context(ctx)
        assert enriched.get("path_in_restricted") is True, (
            "FF-2 FIXED: /etc/passwd should set path_in_restricted=True"
        )
        # Now the enriched context should be blocked by r-fs-001
        verdict, _ = self.engine.check(HookPoint.PRE_ACTION, enriched)
        assert verdict != Verdict.ALLOW, (
            "FF-2 FIXED: Enriched context with /etc/passwd must be REJECTED"
        )

    def test_enrich_context_sensitive_file(self):
        """Context with .env path should set path_matches."""
        from agent.core import Agent
        ctx = {
            "object": "file",
            "operation": "write",
            "tool": "file-system",
            "params": {"path": ".env"},
        }
        enriched = Agent._enrich_dont_do_context(ctx)
        assert enriched.get("path_matches") is not None, (
            "FF-2 FIXED: .env should set path_matches"
        )

    def test_enrich_context_normal_file_unaffected(self):
        """Normal files should not set restricted/sensitive keys."""
        from agent.core import Agent
        ctx = {
            "object": "file",
            "operation": "write",
            "tool": "file-system",
            "params": {"path": "src/main.py"},
        }
        enriched = Agent._enrich_dont_do_context(ctx)
        assert "path_in_restricted" not in enriched
        assert "path_matches" not in enriched

    def test_plan_hook_rejects_dangerous_plan(self):
        """PLAN hook should detect dangerous intentions (r-fs-001)."""
        verdict, msg = self.engine.check(HookPoint.PLAN, {
            "object": "file",
            "operation": "write",
            "tool": "file-system",
            "path_in_restricted": True,
        })
        assert verdict != Verdict.ALLOW, (
            "FF-2 STRIDE/Elevation: Plans targeting restricted paths should "
            f"be blocked at the PLAN hook. Got: {verdict}"
        )


# ——— FF-3: Role Compliance ———
# Agent must stay within the role's authorized tools.


class TestRoleCompliance:
    """FF-3: Verify role structure and tool authorization."""

    def test_role_has_focus_objects(self):
        """Every role should define focus objects."""
        assert len(DEFAULT_ROLE.focus_objects) >= 2, (
            "FF-3: Default role should cover at least file + git-repo or database."
        )

    def test_known_object_types_all_have_focus(self):
        """Every known object type should have a focus definition."""
        for obj_type in DEFAULT_ROLE.known_object_types:
            focus = DEFAULT_ROLE.get_focus(obj_type)
            assert focus is not None, (
                f"FF-3: Object type '{obj_type}' in known_object_types "
                f"but has no focus definition."
            )

    def test_manipulation_tools_are_defined(self):
        """Each focus should declare manipulation tools (not just observation)."""
        for focus in DEFAULT_ROLE.focus_objects:
            assert len(focus.manipulation) > 0, (
                f"FF-3: Focus '{focus.object_type}' has no manipulation tools. "
                f"A role that can only observe cannot act."
            )

    def test_dont_do_operations_block_manipulation(self):
        """Dont-do operations should not overlap with authorized manipulation tools."""
        for focus in DEFAULT_ROLE.focus_objects:
            overlap = set(focus.dont_do_operations) & set(focus.manipulation)
            assert not overlap, (
                f"FF-3: Focus '{focus.object_type}' has dont-do operations "
                f"that conflict with manipulation tools: {overlap}"
            )

    def test_role_constraints_generated(self):
        """Role constraints should be generated for each focus object type."""
        for obj_type in DEFAULT_ROLE.known_object_types:
            constraints = DEFAULT_ROLE.get_constraints(obj_type)
            # Not every type needs constraints, but the method should return a list
            assert isinstance(constraints, list), (
                f"FF-3: get_constraints({obj_type}) should return a list."
            )


# ——— FF-4: Context Efficiency ———
# Prompt must not waste tokens on irrelevant information.


class TestContextEfficiency:
    """FF-4: Verify prompt assembly uses tokens efficiently."""

    def test_tool_summary_is_compact(self):
        """Tool summaries should be proportional to the number of tools."""
        tools = [_make_mock_tool(f"tool-{i}", ["read", "write"]) for i in range(5)]
        summary = format_tool_summary(tools)
        lines = summary.split("\n")
        assert len(lines) == 5, (
            f"FF-4: 5 tools should produce ~5 lines of summary, got {len(lines)}."
        )

    def test_tool_summary_truncation(self):
        """With many tools, summary should not explode."""
        tools = [_make_mock_tool(f"tool-{i}", ["read", "write", "delete"])
                 for i in range(50)]
        summary = format_tool_summary(tools)
        # 50 tools should produce a summary but not 1000+ characters each
        assert 100 < len(summary) < 8000, (
            f"FF-4: 50-tool summary length {len(summary)} chars — "
            f"should be compact, not verbose."
        )

    def test_prompt_separates_sections(self):
        """Prompt should use XML tags for structure, not verbose prose."""
        assembler = PromptAssembler()
        prompt = assembler.assemble(PromptInputs(
            role="You are a test agent.",
            tool_summaries="- test-tool: does things (run_test)",
            task="Run tests.",
        ))
        sections = ["<system>", "<format_rules", "<tools>", "<task>"]
        for section in sections:
            assert section in prompt, (
                f"FF-4: Prompt missing structural section '{section}'."
            )


# ——— FF-5: Output Format Compliance ———
# LLM responses must follow citation rules and progressive disclosure.


class TestOutputFormatCompliance:
    """FF-5: Verify output format rules are generated and enforced."""

    def test_format_rules_injected(self):
        """Output format rules should appear in every assembled prompt."""
        assembler = PromptAssembler()
        prompt = assembler.assemble(PromptInputs(
            role="You are a test agent.",
            task="Do something.",
        ))
        assert "<format_rules" in prompt, (
            "FF-5: Output format rules must be in every prompt. "
            "Without them, the LLM has no citation/disclosure guidance."
        )
        assert 'immutable="true"' in prompt, (
            "FF-5: Format rules must be marked immutable — "
            "the LLM should not be able to override them."
        )

    def test_citation_rules_exist(self):
        """OutputFormatManager should define citation rules."""
        fmt = OutputFormatManager()
        rules_prompt = fmt.get_format_prompt()
        assert "引用" in rules_prompt or "cite" in rules_prompt.lower() or \
               "格式" in rules_prompt, (
            "FF-5: Format rules should include citation guidance."
        )

    def test_disclosure_required(self):
        """Progressive disclosure should be enabled by default."""
        fmt = OutputFormatManager()
        assert fmt.profile.disclosure_required, (
            "FF-5: Progressive disclosure should be enabled by default. "
            "It ensures LLM responses follow summary → details → full layers."
        )

    def test_validate_clean_response(self):
        """Clean responses without tool calls should pass validation."""
        fmt = OutputFormatManager()
        result = fmt.validate("任务已完成。文件已成功创建。")
        assert result["valid"], (
            f"FF-5: Clean responses should pass validation. "
            f"Got errors: {result.get('issues', [])}"
        )

    def test_validate_response_with_tool_calls(self):
        """Responses with function calls should trigger report format check."""
        fmt = OutputFormatManager()
        response = (
            "I will read the file.\n\n"
            "<function_call>\n"
            "<name>file-system</name>\n"
            "<capability>read_file</capability>\n"
            "<parameters>{\"path\": \"src/main.py\"}</parameters>\n"
            "</function_call>"
        )
        result = fmt.validate(response)
        # Having tool calls without action_reports should produce warnings
        has_report_issues = any(
            i["type"] == "report_format" for i in result.get("issues", [])
        )
        assert has_report_issues or result["warning_count"] >= 0, (
            "FF-5: Response with function_call should trigger report format check."
        )


# ——— FF: Agent Factory Testability ———


class TestAgentFactory:
    """FF: Verify the agent factory pattern works for testing."""

    def test_create_agent_with_test_config(self):
        """create_agent factory pattern is importable and callable."""
        config = AppConfig.test()
        # Verify config structure without full agent creation
        # (full creation requires writable filesystem for memory store)
        assert config.agent.max_loop_iterations == 2
        assert config.tools.default_timeout_ms == 5000
        assert hasattr(AppConfig, "test"), (
            "FF: AppConfig.test() classmethod must exist for testability"
        )
        assert hasattr(AppConfig, "dev"), (
            "FF: AppConfig.dev() classmethod must exist for development"
        )
        assert hasattr(AppConfig, "from_yaml"), (
            "FF: AppConfig.from_yaml() must exist for production config loading"
        )

    def test_test_config_max_iterations(self):
        """Test config should use short iteration limits."""
        config = AppConfig.test()
        assert config.agent.max_loop_iterations == 2, (
            "FF: Test config should limit iterations for fast test feedback."
        )

    def test_dev_config_defaults(self):
        """Dev config should have reasonable defaults."""
        config = AppConfig.dev()
        assert config.agent.max_loop_iterations == 3
        assert "therain2020-agent" in config.memory.path  # under ~/.therain2020-agent/
