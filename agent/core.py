"""Agent Core — event loop with TODO mode execution. Phase 1."""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from .config import AppConfig, load_config
from .consolidation import ConsolidationDaemon
from .correction import (
    Correction,
    correction_to_rule,
    parse_correction_file,
    persist_dont_do_rule,
)
from .dont_do import DontDoEngine, HookPoint, Verdict
from .errors import InterruptSignal
from .event_store import EventStore
from .events import (
    correction_applied,
    error_occurred,
    goal_completed,
    goal_started,
    goal_verified,
    object_observed,
    plan_generated,
    rule_added,
    tool_called,
    tool_result,
)
from .interrupt import InterruptHandler
from .memory import EpisodeEntry, EpisodicMemory
from .objects import AgentObject, ObjectState, build_object_context, extract_state_properties
from .output_format import OutputFormatManager
from .pattern_miner import PatternMiner
from .prompt import (
    PromptAssembler,
    PromptInputs,
    ToolResultManager,
    format_tool_summary,
)
from .providers import LLMProvider, ProviderConfig
from .providers.router import CostRouter
from .retry import retry
from .role import DEFAULT_ROLE
from .security import SecurityManager
from .tools.editor import AgentToolEditor
from .tools.evolution import ToolEvolutionManager
from .tools.executor import ToolExecutor, VerificationResult
from .tools.registry import ToolRegistry
from .tools.supervisor import ImportedToolSupervisor

logger = structlog.get_logger()


class Agent:
    """Agent core with TODO-mode execution.

    Phase 1: Processes TODO lists step by step.
    Phase 2 will add Goal-mode planning.
    """

    def __init__(self, config_path: Path | None = None,
                 config_dict: dict | None = None):
        self.config = config_dict if config_dict is not None else load_config(config_path)
        self.session_id = str(uuid.uuid4())[:8]

        # Components
        self.registry = ToolRegistry(self.config["tools"]["scan_paths"])
        self.supervisor = ImportedToolSupervisor()
        self.executor = ToolExecutor(supervisor=self.supervisor)
        self.security = SecurityManager(self.config["security"]["dont_do_paths"])
        self.memory = EpisodicMemory(self.config["memory"]["path"])
        self.event_store = EventStore(self.memory.store.conn)
        self.consolidation = ConsolidationDaemon(
            store=self.memory.store,
            provider=self._provider
        )
        self.interrupt = InterruptHandler()
        self.output_format = OutputFormatManager()
        self.prompt_assembler = PromptAssembler(output_format=self.output_format)
        self.tool_result_mgr = ToolResultManager()
        self.dont_do = DontDoEngine()
        self.role = DEFAULT_ROLE

        # LLM Provider (lazy)
        self._provider: LLMProvider | None = None
        self._provider_config: ProviderConfig | None = None

        # Phase 1: runtime tracking
        self._non_set_changes: list[dict] = []
        self._observed_objects: dict = {}

        # Phase 3: correction tracking
        self._corrections: list[Correction] = []
        self._pending_corrections: list[Correction] = []

        # Phase 3: capability routing + pattern mining
        self.router = CostRouter()
        self._pattern_miner: PatternMiner | None = None

        # Phase 4: self-healing tool evolution (九-C + 十-A)
        self.evolution = ToolEvolutionManager(
            tools_dir=self.config.get("tools", {}).get("scan_paths", ["./tools"])[0]
        )
        self.tool_editor = AgentToolEditor(self.evolution)
        self._current_episode_id: str = ""

    def set_provider(self, provider: LLMProvider, config: ProviderConfig) -> None:
        """Set the LLM provider."""
        self._provider = provider
        self._provider_config = config
        logger.info("provider_set", name=provider.name, model=provider.model)

    def setup(self) -> None:
        """Initialize all subsystems."""
        self.registry.scan()
        self.security.load_rules()
        self.dont_do.load_rules(self.config["security"]["dont_do_paths"])
        self.interrupt.setup()
        logger.info("agent_setup",
                     session=self.session_id,
                     tools=len(self.registry.list_all()),
                     dont_do_rules=len(self.security.list_rules()),
                     runtime_rules=len(self.dont_do.list_rules()))

    def teardown(self) -> None:
        """Clean up all subsystems."""
        self.interrupt.teardown()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.supervisor.shutdown_all())
        except RuntimeError:
            # No running event loop, skip async cleanup
            pass

    def _track_non_set_change(self, action: str, rule_id: str,
                               reason: str, context: dict) -> None:
        """Record a dont-do rule change for later persistence."""
        self._non_set_changes.append({
            "time": datetime.now(UTC).isoformat(),
            "action": action,
            "rule_id": rule_id,
            "reason": reason,
            "context": context,
        })

    def _capture_object_states(self) -> tuple[dict, dict, list]:
        """Extract serializable state snapshots from observed objects."""
        before = {}
        after = {}
        changes = []
        for uri, obj in self._observed_objects.items():
            sb = getattr(obj, "state_before", None)
            sa = getattr(obj, "state_after", None)
            if sb and hasattr(sb, "properties"):
                before[uri] = sb.properties
            if sa and hasattr(sa, "properties"):
                after[uri] = sa.properties
            if hasattr(obj, "state_changed") and obj.state_changed:
                diff = obj.diff if hasattr(obj, "diff") else {}
                for k, v in diff.items():
                    changes.append({
                        "uri": uri, "field": k,
                        "before": v.get("before"), "after": v.get("after"),
                    })
        return before, after, changes

    # Paths that should never be written to by an agent
    _RESTRICTED_PREFIXES = (
        "/etc/", "/boot/", "/sys/", "/proc/", "/dev/",
        "C:\\Windows\\", "C:\\Windows\\System32\\",
        "/System/", "/Library/",
    )
    _SENSITIVE_FILES = (".env", ".git", "credentials", "secrets", ".pem", ".key")

    @staticmethod
    def _enrich_dont_do_context(ctx: dict) -> dict:
        """Add path-based match keys to dont-do context.

        Extracts path from params and sets path_in_restricted and
        path_matches so that r-fs-001 and r-fs-002 can match.
        """
        params = ctx.get("params", {})
        path = params.get("path", params.get("file", params.get("uri", "")))
        if not path:
            return ctx

        enriched = dict(ctx)

        # Check restricted prefixes
        path_lower = path.lower().replace("\\", "/")
        for prefix in Agent._RESTRICTED_PREFIXES:
            prefix_lower = prefix.lower().replace("\\", "/")
            if path_lower.startswith(prefix_lower):
                enriched["path_in_restricted"] = True
                break

        # Check sensitive file patterns
        basename = path_lower.rsplit("/", 1)[-1]
        for sensitive in Agent._SENSITIVE_FILES:
            if sensitive.lower() in basename or basename.startswith(sensitive.lower()):
                enriched["path_matches"] = sensitive
                break

        return enriched

    def _check_dont_do(self, hook: HookPoint, ctx: dict) -> tuple[Verdict, str]:
        """Check dont-do rules at a hook point. Returns (verdict, message).

        Context is enriched with path-based match keys before checking,
        so that r-fs-001 (path_in_restricted) and r-fs-002 (path_matches)
        can actually fire.
        """
        enriched = self._enrich_dont_do_context(ctx)
        verdict, msg = self.dont_do.check(hook, enriched)
        if verdict != Verdict.ALLOW:
            self._track_non_set_change(
                "hit", ctx.get("rule_id", "unknown"),
                msg, enriched
            )
        return verdict, msg

    # ——— Correction handling (Phase 3) ———

    async def _check_for_corrections(self) -> list[Correction]:
        """Poll for user corrections from the corrections/ directory."""
        corrections_dir = Path("corrections")
        if not corrections_dir.exists():
            return []
        found = []
        for f in sorted(corrections_dir.glob("*.yaml")):
            correction = parse_correction_file(f)
            if correction and not correction.applied:
                found.append(correction)
                self._pending_corrections.append(correction)
                try:
                    f.unlink()
                except OSError:
                    pass
        return found

    async def _apply_correction(self, correction: Correction,
                                  task_id: str = "") -> None:
        """Apply a correction: generate dont-do rule + persist."""
        rule = await correction_to_rule(correction, self._get_provider())
        if rule:
            self.dont_do.add_rule(rule)
            persist_dont_do_rule(rule)
            correction.generated_rule_id = rule.id
            self._track_non_set_change(
                "add", rule.id,
                f"User correction: {correction.description[:100]}",
                correction.to_context(),
            )
            # Event Sourcing: safety-critical rule addition (synchronous)
            if task_id:
                self.event_store.append(correction_applied(
                    task_id, correction.id, rule.id, correction.description,
                ))
                self.event_store.append(rule_added(
                    task_id, rule.id, rule.description,
                ))
        correction.applied = True
        self._corrections.append(correction)
        logger.info("correction_applied", corr_id=correction.id,
                     rule_id=correction.generated_rule_id)

    async def _replan_with_corrections(self, goal: str, observation: str,
                                         corrections: list[Correction],
                                         conversation: str) -> list[dict]:
        """Re-plan considering user corrections."""
        corrections_text = "\n".join(
            f"- [{c.severity.value}] {c.target_uri}: {c.description}\n  建议: {c.suggestion}"
            for c in corrections
        )
        prompt = self.prompt_assembler.assemble(PromptInputs(
            role=(
                "基于观察结果和用户纠正，重新制定执行计划。"
                "避开用户纠正中指出的问题，采纳用户建议。"
                "输出 JSON 格式的计划数组。"
            ),
            task=(
                f"目标: {goal}\n\n"
                f"观察结果:\n{observation}\n\n"
                f"用户纠正（必须遵守）:\n{corrections_text}\n\n"
                f"之前的执行记录:\n{conversation[-2000:]}"
            ),
        ))
        resp = await retry(self._get_provider().complete, prompt, max_tokens=2048)
        try:
            import json
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            if "[" in text and "]" in text:
                text = text[text.find("["):text.rfind("]") + 1]
            return json.loads(text)
        except json.JSONDecodeError:
            return [{"action": resp.content[:500], "verify": "manual"}]

    # ——— TODO analysis (Phase 3) ———

    async def _analyze_todo(self, task: str) -> dict:
        """Analyze a TODO for completeness and clarity."""
        prompt = f"""分析以下 TODO 任务。

TODO: {task}

判断:
1. 描述是否清晰？要做什么是否明确？
2. 是否包含验收标准（如何判断完成）？
3. 任务涉及哪些对象（文件、数据库等）？
4. 有没有模糊、不合理或缺失的地方？

输出 JSON:
{{
  "is_clear": true/false,
  "has_acceptance_criteria": true/false,
  "objects_involved": [{{"uri": "file://...", "type": "file"}}],
  "acceptance_criteria": ["完成标准1"],
  "issues": [
    {{"type": "unclear|missing|unreasonable", "severity": "blocker|warning",
      "description": "...", "suggested_fix": "..."}}
  ],
  "suggested_approach": "..."
}}"""
        resp = await self._get_provider().complete(prompt, max_tokens=1000)
        try:
            import json
            text = resp.content.strip()
            if "{" in text and "}" in text:
                text = text[text.find("{"):text.rfind("}") + 1]
            return json.loads(text)
        except json.JSONDecodeError:
            return {"is_clear": True, "has_acceptance_criteria": False,
                    "objects_involved": [], "acceptance_criteria": [], "issues": []}

    @staticmethod
    def _prompt_user_for_todo_clarification(
        issues: list[dict], has_criteria: bool
    ) -> str | None:
        """Ask the user to clarify unclear/missing TODO details.

        Returns user input string, or None to skip.
        """
        lines = []
        if issues:
            lines.append("TODO 分析发现问题:")
            for i, issue in enumerate(issues):
                sev = issue.get("severity", "warning")
                desc = issue.get("description", "")
                fix = issue.get("suggested_fix", "")
                lines.append(f"  [{sev}] {desc}")
                if fix:
                    lines.append(f"        建议: {fix}")
        if not has_criteria:
            lines.append("  [blocker] 缺少验收标准——如何判断任务已完成？")
        lines.append("\n请补充说明 (或输入 skip 跳过):")

        try:
            return input("\n".join(lines) + "\n> ").strip()
        except (EOFError, OSError):
            logger.warning("todo_clarification_input_failed")
            return None

    async def _verify_against_criteria(self, criteria: list[str],
                                         conversation: str) -> dict:
        """Verify each acceptance criterion against execution results."""
        if not criteria:
            return {"all_met": True, "criteria_results": [], "met_count": 0, "total_count": 0}
        results = []
        for criterion in criteria:
            prompt = f"""基于执行记录，判断以下验收标准是否满足。

验收标准: {criterion}
执行记录 (最后3000字符): {conversation[-3000:]}

只回复 YES 或 NO，然后简短说明原因。"""
            resp = await self._get_provider().complete(prompt, max_tokens=100)
            met = "YES" in resp.content.upper()
            results.append({
                "criterion": criterion,
                "met": met,
                "evidence": resp.content[:200],
            })
        return {
            "all_met": all(r["met"] for r in results),
            "criteria_results": results,
            "met_count": sum(1 for r in results if r["met"]),
            "total_count": len(results),
        }

    def _get_provider(self) -> LLMProvider:
        """Get or raise if no provider configured."""
        if self._provider is None:
            raise RuntimeError(
                "No LLM provider configured. "
                "Run: therain2020-agent provider add <name> --api-key-env <ENV_VAR> --model <model>"
            )
        return self._provider

    async def run(self, task_description: str) -> dict:
        """Execute a task in TODO mode.

        Flow:
        1. Load context (tools, dont-do, memory)
        2. Send to LLM → get action plan
        3. Execute each step → check interrupts
        4. Loop until done or max iterations (3)
        5. Record episode
        """
        if self._provider is None:
            self._provider = self._get_provider()

        max_iterations = self.config["agent"].get("max_loop_iterations", 3)
        task_id = str(uuid.uuid4())[:8]
        tools_used: list[str] = []
        steps_taken = 0
        start_time = time.time()
        last_error = ""

        logger.info("task_start", task_id=task_id, task=task_description[:200])
        self._current_episode_id = task_id

        # Phase 3: Analyze TODO for clarity and acceptance criteria
        analysis = await self._analyze_todo(task_description)
        acceptance_criteria = analysis.get("acceptance_criteria", [])
        issues = analysis.get("issues", [])
        if issues or not analysis.get("has_acceptance_criteria", False):
            logger.warning("todo_issues_found", task_id=task_id,
                           issues=len(issues), missing_criteria=not analysis.get("has_acceptance_criteria"))
            # Ask user for clarification
            clarification = self._prompt_user_for_todo_clarification(
                issues, analysis.get("has_acceptance_criteria", False)
            )
            if clarification:
                task_description = f"{task_description}\n\n用户补充说明:\n{clarification}"
                analysis = await self._analyze_todo(task_description)
                acceptance_criteria = analysis.get("acceptance_criteria", [])

        conversation = ""
        result_summary = ""

        # Phase 4: dual-mode scheduler — exploit vs explore
        exec_mode, mode_info = await self._select_mode(task_description)

        criteria_text = ""
        if acceptance_criteria:
            criteria_text = (
                "\n\n验收标准（必须全部满足）:\n" +
                "\n".join(f"- {c}" for c in acceptance_criteria)
            )
        mode_context = self._inject_mode_context(exec_mode, mode_info)
        if mode_context:
            criteria_text = mode_context + "\n" + criteria_text

        # Adjust iterations based on mode
        effective_max_iter = max_iterations
        if exec_mode.value == "exploit":
            effective_max_iter = min(max_iterations, 2)

        for iteration in range(effective_max_iter):
            await self.interrupt.check()

            # Build prompt
            tools = self.registry.list_all()
            relevant_objects = list(set(
                obj for t in tools for obj in t.objects
            ))

            role_text = (
                "你是一个编程助手。按照用户的任务指令逐步执行。\n"
                "完成所有验收标准后再结束。\n\n"
                "当你需要使用工具时，必须用以下格式输出：\n"
                "<function_call>\n"
                "<name>工具名称</name>\n"
                "<capability>能力名称</capability>\n"
                "<parameters>{\"参数名\": \"参数值\"}</parameters>\n"
                "</function_call>\n\n"
                "收到工具结果后，根据结果继续执行或给出最终回答。\n"
                "如果任务已完成，给出最终回答，不要继续调用工具。"
            )

            prompt = self.prompt_assembler.assemble(PromptInputs(
                role=role_text,
                dont_do_rules=self.security.get_constraints_prompt(relevant_objects),
                tool_summaries=format_tool_summary(tools),
                task=task_description + criteria_text,
                conversation_summary=result_summary if iteration > 0 else "",
                recent_messages=conversation,
            ))

            # Call LLM
            provider = self._get_provider()
            try:
                response = await retry(
                    provider.complete,
                    prompt,
                    max_tokens=4096,
                    context={"task_id": task_id, "iteration": iteration + 1},
                )
            except Exception as e:
                last_error = str(e)
                logger.error("llm_call_failed", task_id=task_id, error=last_error)
                break

            logger.info("llm_response", task_id=task_id,
                         iteration=iteration + 1,
                         content=response.content[:300])

            # Validate output format
            fmt_result = self.output_format.validate(response.content)
            if not fmt_result["valid"] or fmt_result["warning_count"] > 0:
                logger.info("format_issues", task_id=task_id,
                            warnings=fmt_result["warning_count"],
                            errors=fmt_result["error_count"])

            conversation += f"\n[Step {iteration + 1}] {response.content[:500]}"
            result_summary = f"第 {iteration + 1} 轮: {response.content[:300]}"

            # Parse tool calls from response
            tool_calls = self._parse_tool_calls(response.content)
            if not tool_calls:
                # No tool calls → LLM gave final answer
                result_summary = response.content[:500]
                break

            # Execute tool calls
            for tc in tool_calls:
                await self.interrupt.check()

                tool_def = self.registry.get(tc["tool"])
                if not tool_def:
                    conversation += f"\n[Error] 未找到工具: {tc['tool']}"
                    continue

                # PRE_ACTION dont-do check
                obj_type = tool_def.objects[0] if tool_def.objects else "unknown"
                verdict, msg = self._check_dont_do(HookPoint.PRE_ACTION, {
                    "object": obj_type,
                    "operation": tc["capability"],
                    "tool": tc["tool"],
                    "params": tc.get("params", {}),
                })
                if verdict == Verdict.REJECT:
                    conversation += f"\n[Blocked] {msg}"
                    continue
                elif verdict == Verdict.WARN:
                    conversation += f"\n[Warning] {msg}"

                try:
                    # Phase 4: execute with verification (十-A)
                    result, verify_result = await self.executor.execute_and_verify(
                        tool_def, tc["capability"], tc.get("params", {})
                    )
                    tools_used.append(f"{tc['tool']}.{tc['capability']}")
                    steps_taken += 1

                    result_str = str(result)[:2000]
                    conversation += f"\n[Result from {tc['tool']}.{tc['capability']}]: {result_str}"

                    # Check verification
                    if verify_result and not verify_result.verified:
                        logger.warning("silent_failure_detected",
                                       tool=tc["tool"], capability=tc["capability"],
                                       diff=verify_result.diff)
                        conversation += (
                            f"\n[VERIFICATION FAILED] {verify_result.expected_effect}\n"
                            f"Diff: {verify_result.diff}"
                        )
                        if verify_result.suggestion:
                            conversation += f"\nSuggestion: {verify_result.suggestion}"
                        # Trigger self-healing to fix the verify or tool
                        healed = await self._handle_verification_failure(
                            verify_result, tc["tool"], tc["capability"],
                            tc.get("params", {}), conversation
                        )
                        if healed:
                            conversation += "\n[Self-Healing] Verification fixed, retry suggested"

                    # POST_ACTION dont-do check
                    self._check_dont_do(HookPoint.POST_ACTION, {
                        "object": obj_type,
                        "operation": tc["capability"],
                        "tool": tc["tool"],
                        "result": result_str[:500],
                    })

                except InterruptSignal:
                    raise
                except Exception as e:
                    last_error = str(e)
                    conversation += f"\n[Error] {tc['tool']}.{tc['capability']}: {e}"

                    # Phase 4: attempt self-healing on tool failures
                    healed = await self._handle_tool_failure(
                        e, tc["tool"], tc["capability"],
                        tc.get("params", {}), conversation
                    )
                    if healed:
                        conversation += "\n[Self-Healing] Tool fixed, retry suggested"

        # Verify acceptance criteria
        verification = None
        if acceptance_criteria:
            verification = await self._verify_against_criteria(
                acceptance_criteria, conversation
            )

        # Record episode
        success = (
            not last_error
            and (verification["all_met"] if verification else True)
        )
        objects_before, objects_after, object_changes = self._capture_object_states()
        self.memory.log_episode(EpisodeEntry(
            task_id=task_id,
            task_type="todo",
            task_summary=task_description[:200],
            tools_used=list(set(tools_used)),
            steps=steps_taken,
            success=success,
            error=last_error,
            non_set_changes=self._non_set_changes,
            objects_before=objects_before,
            objects_after=objects_after,
            object_changes=object_changes,
        ))

        duration = round(time.time() - start_time, 1)
        logger.info("task_complete", task_id=task_id, success=success,
                     steps=steps_taken, duration_seconds=duration)

        # Phase 3: Record capability result for routing
        self._record_capability_result(task_description, success, steps_taken)

        # Trigger consolidation
        self.consolidation.on_task_end(interrupted=not success)
        self.consolidation.set_provider(self._get_provider())
        should, reason = self.consolidation.should_consolidate()
        if should:
            logger.info("consolidation_triggered", reason=reason)
            try:
                await self.consolidation.consolidate()
            except Exception as e:
                logger.error("consolidation_error", error=str(e))

        return {
            "task_id": task_id,
            "success": success,
            "steps": steps_taken,
            "tools_used": list(set(tools_used)),
            "duration_seconds": duration,
            "result": result_summary,
            "error": last_error,
            "verification": verification,
        }

    # ——— Goal Mode (K8s reconciliation loop) ———

    async def goal_run(self, goal: str) -> dict:
        """Execute a goal. 类比: Kubernetes controller reconciliation loop.

        Observe → Analyze → Plan → Execute → Verify → (loop)
        """
        max_iterations = self.config["agent"].get("max_loop_iterations", 3)
        task_id = str(uuid.uuid4())[:8]
        tools_used: list[str] = []
        steps_taken = 0
        start_time = time.time()
        last_error = ""

        logger.info("goal_start", task_id=task_id, goal=goal[:200])
        self._current_episode_id = task_id
        conversation = ""
        self.event_store.append(goal_started(task_id, goal))

        for iteration in range(max_iterations):
            await self.interrupt.check()

            if iteration == 0:
                # Phase 1 V2: Structured Observe
                objects = await self._observe_structured(goal)
                observation_lines = []
                for uri, obj in objects.items():
                    state = obj.state_before.properties if obj.state_before else {}
                    observation_lines.append(f"[{obj.type}] {obj.display_name}: {state}")
                observation = "\n".join(observation_lines) if observation_lines else "(no objects observed)"
                conversation += f"\n[Observe] {len(objects)} objects: {observation[:500]}"

                # Event Sourcing: record observations
                for uri, obj in objects.items():
                    state = obj.state_before.properties if obj.state_before else {}
                    self.event_store.append(object_observed(task_id, uri, obj.type, state))

                # Phase 2: Analyze + Plan
                plan = await self._plan_goal(goal, observation, conversation)
                if not plan:
                    last_error = "LLM did not produce a plan"
                    break
                # PLAN hook: filter steps that violate dont-do rules
                plan = self._filter_plan_by_dont_do(plan)
                if not plan:
                    last_error = "All plan steps rejected by dont-do rules"
                    self.event_store.append(error_occurred(task_id, "PlanError", last_error))
                    break
                conversation += f"\n[Plan] {len(plan)} steps generated"
                self.event_store.append(plan_generated(task_id, plan))
            else:
                # Retry: check for user corrections, then replan
                corrections = await self._check_for_corrections()
                for corr in corrections:
                    await self._apply_correction(corr, task_id=task_id)

                observation = f"Previous attempt failed. {conversation[-2000:]}"
                if corrections:
                    plan = await self._replan_with_corrections(
                        goal, observation, corrections, conversation
                    )
                else:
                    plan = await self._plan_goal(goal, observation, conversation)
                if not plan:
                    break
                plan = self._filter_plan_by_dont_do(plan)

            # Phase 3: Execute
            for step in plan:
                await self.interrupt.check()
                try:
                    # Execute the step as if it's a TODO item
                    tools = self.registry.list_all()
                    role_text = (
                        "执行以下步骤。用 function_call 格式调用工具。"
                        "完成后不要继续，输出 <final>done</final>。"
                    )
                    prompt = self.prompt_assembler.assemble(PromptInputs(
                        role=role_text,
                        tool_summaries=format_tool_summary(tools),
                        task=step.get("action", str(step)),
                        conversation_summary=conversation[-3000:],
                    ))
                    provider = self._get_provider()
                    resp = await retry(provider.complete, prompt, max_tokens=2048)
                    tool_calls = self._parse_tool_calls(resp.content)
                    for tc in tool_calls:
                        tool_def = self.registry.get(tc["tool"])
                        if not tool_def:
                            continue
                        # PRE_ACTION dont-do check
                        obj_type = tool_def.objects[0] if tool_def.objects else "unknown"
                        verdict, msg = self._check_dont_do(HookPoint.PRE_ACTION, {
                            "object": obj_type,
                            "operation": tc["capability"],
                            "tool": tc["tool"],
                            "params": tc.get("params", {}),
                        })
                        if verdict == Verdict.REJECT:
                            conversation += f"\n[Blocked] {msg}"
                            continue
                        elif verdict == Verdict.WARN:
                            conversation += f"\n[Warning] {msg}"

                        # Event Sourcing: tool called
                        self.event_store.append(tool_called(
                            task_id, tc["tool"], tc["capability"],
                            tc.get("params", {}),
                        ))

                        result = await self.executor.execute(
                            tool_def, tc["capability"], tc.get("params", {})
                        )
                        tools_used.append(f"{tc['tool']}.{tc['capability']}")
                        steps_taken += 1
                        result_str = str(result)[:500]

                        # Event Sourcing: tool result
                        self.event_store.append(tool_result(
                            task_id, tc["tool"], tc["capability"],
                            result_str, success=True,
                        ))
                        conversation += (
                            f"\n[Result from {tc['tool']}.{tc['capability']}]: "
                            f"{result_str}"
                        )

                        # POST_ACTION dont-do check
                        self._check_dont_do(HookPoint.POST_ACTION, {
                            "object": obj_type,
                            "operation": tc["capability"],
                            "tool": tc["tool"],
                            "result": result_str,
                        })
                except InterruptSignal:
                    raise
                except Exception as e:
                    conversation += f"\n[Error] {step.get('action', str(step))[:100]}: {e}"
                    self.event_store.append(error_occurred(
                        task_id, type(e).__name__, str(e),
                    ))

            # Phase 4 V2: Structured Verify
            verification = await self._verify_goal(goal, conversation)
            self.event_store.append(goal_verified(
                task_id, verification.get("achieved", False),
                verification.get("confidence", 0),
                verification.get("explanation", ""),
            ))
            if verification.get("achieved") and verification.get("confidence", 0) >= 0.6:
                last_error = ""
                break
            last_error = (
                f"Goal not verified: {verification.get('explanation', 'unknown')[:200]}"
            )
            conversation += (
                f"\n[Verify failed] confidence={verification.get('confidence', 0):.1f}, "
                f"unmet={verification.get('unmet', [])}"
            )

        # Event Sourcing: completion
        success = not last_error
        duration = round(time.time() - start_time, 1)
        self.event_store.append(goal_completed(task_id, success,
                                                steps_taken, duration))
        self.event_store.maybe_snapshot(task_id)

        # Record episode
        objects_before, objects_after, object_changes = self._capture_object_states()
        self.memory.log_episode(EpisodeEntry(
            task_id=task_id, task_type="goal", task_summary=goal[:200],
            tools_used=list(set(tools_used)), steps=steps_taken,
            success=success, error=last_error,
            non_set_changes=self._non_set_changes,
            objects_before=objects_before,
            objects_after=objects_after,
            object_changes=object_changes,
        ))

        # Phase 3: Record capability result
        self._record_capability_result(goal, success, steps_taken)

        # Consolidation trigger
        self.consolidation.on_task_end(interrupted=not success)
        self.consolidation.set_provider(self._get_provider())
        should, reason = self.consolidation.should_consolidate()
        if should:
            try:
                await self.consolidation.consolidate()
            except Exception as e:
                logger.error("consolidation_error", error=str(e))

        duration = round(time.time() - start_time, 1)
        logger.info("goal_complete", task_id=task_id, success=success,
                     steps=steps_taken, duration_seconds=duration)
        return {
            "task_id": task_id, "success": success, "steps": steps_taken,
            "tools_used": list(set(tools_used)),
            "duration_seconds": duration, "error": last_error,
        }

    def _filter_plan_by_dont_do(self, plan: list[dict]) -> list[dict]:
        """Filter plan steps through PLAN hook dont-do rules."""
        filtered = []
        for step in plan:
            action = step.get("action", str(step))
            tool = step.get("tool", "")
            obj = step.get("object", "unknown")
            verdict, msg = self._check_dont_do(HookPoint.PLAN, {
                "object": obj,
                "operation": action[:100],
                "tool": tool,
            })
            if verdict == Verdict.REJECT:
                logger.warning("plan_step_rejected", step=action[:100], reason=msg)
                continue
            elif verdict == Verdict.WARN:
                logger.warning("plan_step_warned", step=action[:100], reason=msg)
                step["_warning"] = msg
            filtered.append(step)
        return filtered

    async def _identify_objects_in_goal(self, goal: str) -> list[str]:
        """Let LLM identify which object types are involved in the goal."""
        if not self._provider:
            return self.role.known_object_types
        known = ", ".join(self.role.known_object_types)
        prompt = (
            f"目标: {goal}\n\n"
            f"可用对象类型: {known}\n\n"
            f"只回复 JSON 数组，列出目标涉及的对象类型。示例: [\"file\", \"database\"]"
        )
        try:
            resp = await self._get_provider().complete(prompt, max_tokens=80)
            import json
            text = resp.content.strip()
            if "[" in text and "]" in text:
                text = text[text.find("["):text.rfind("]") + 1]
            types = json.loads(text)
            return [t for t in types if t in self.role.known_object_types]
        except Exception:
            return self.role.known_object_types

    async def _observe_structured(self, goal: str) -> dict[str, AgentObject]:
        """Phase 1 V2: Structured observation with object model.

        1. Identify object types involved in the goal
        2. For each type, use role-defined observation tools only
        3. Build AgentObject instances with state snapshots
        """
        obj_types = await self._identify_objects_in_goal(goal)
        objects: dict[str, AgentObject] = {}

        for obj_type in obj_types:
            # Get tools capable of observing this object type
            obs_caps = self.role.get_observation_tools(obj_type)
            tools = self.registry.find_by_object(obj_type)
            obs_tools = [
                t for t in tools
                if any(c.name in obs_caps for c in t.capabilities)
            ]
            if not obs_tools:
                obs_tools = tools[:3]  # fallback: first 3 tools for this type

            prompt = self.prompt_assembler.assemble(PromptInputs(
                role=(
                    f"观察所有 {obj_type} 类型对象的状态。"
                    "使用提供的工具。完成后输出 <final>done</final>。"
                ),
                tool_summaries=format_tool_summary(obs_tools),
                task=f"目标: {goal}\n\n观察 {obj_type} 对象的当前状态。",
            ))
            provider = self._get_provider()
            try:
                resp = await retry(provider.complete, prompt, max_tokens=4096)
            except Exception:
                continue
            tool_calls = self._parse_tool_calls(resp.content)

            for tc in tool_calls:
                tool_def = self.registry.get(tc["tool"])
                if not tool_def:
                    continue
                result = await self.executor.execute(
                    tool_def, tc["capability"], tc.get("params", {})
                )
                params = tc.get("params", {})
                path = params.get("path", params.get("uri", ""))
                uri = f"{obj_type}://{path}" if path else f"{obj_type}://{tc['tool']}"
                properties = extract_state_properties(result)
                objects[uri] = AgentObject(
                    uri=uri,
                    type=obj_type,
                    display_name=path or tc["tool"],
                    state_before=ObjectState(
                        observed_at=datetime.now(UTC).isoformat(),
                        properties=properties,
                    ),
                    observation_tools=obs_caps,
                    manipulation_tools=self.role.get_manipulation_tools(obj_type),
                    constraints=self.role.get_constraints(obj_type),
                    available_actions=self.role.get_actions(obj_type),
                )

        self._observed_objects = objects
        return objects

    async def _plan_goal(self, goal: str, observation: str, conversation: str) -> list[dict]:
        """Phase 2+3: Analyze gap and generate plan.

        V2: Uses object-filtered tools in the planning prompt for better relevance.
        """
        obj_types = []
        for obj in self._observed_objects.values():
            if obj.type not in obj_types:
                obj_types.append(obj.type)

        # Filter tools to only those relevant to identified objects
        relevant_tools = []
        for obj_type in obj_types:
            relevant_tools.extend(self.registry.find_by_object(obj_type))
        if not relevant_tools:
            relevant_tools = self.registry.list_all()[:10]

        object_context = build_object_context(self._observed_objects)

        prompt = self.prompt_assembler.assemble(PromptInputs(
            role=(
                "基于观察结果和对象上下文，使用可用工具为目标制定执行计划。"
                "注意每个对象的约束(Constraints)和可用操作(Actions)。"
                "输出 JSON 格式的计划数组，每步包含 action, tool, object 和 verify。"
                "如果不可自动验证，设置 verify: 'manual'。"
                "不要在 JSON 之外输出任何内容。"
            ),
            tool_summaries=format_tool_summary(relevant_tools),
            object_context=object_context,
            task=(
                f"目标: {goal}\n\n"
                f"观察结果:\n{observation}"
            ),
            conversation_summary=conversation[-2000:],
        ))
        provider = self._get_provider()
        resp = await retry(provider.complete, prompt, max_tokens=2048)
        try:
            import json
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            if "[" in text and "]" in text:
                text = text[text.find("["):text.rfind("]") + 1]
            return json.loads(text)
        except json.JSONDecodeError:
            return [{"action": resp.content[:500], "verify": "manual"}]

    async def _verify_goal(self, goal: str, conversation: str) -> dict:
        """Phase 5 V2: Structured verification with active state observation.

        Re-observes objects to compare final vs initial state,
        then judges goal achievement with evidence.
        """
        # Re-observe objects to get final state
        objects_after = await self._observe_structured(goal)

        # Update state_after on previously observed objects
        for uri, obj in self._observed_objects.items():
            if uri in objects_after:
                obj.state_after = objects_after[uri].state_before

        # Build state diff
        state_diff = {}
        for uri, obj in self._observed_objects.items():
            if obj.state_changed:
                state_diff[uri] = obj.diff

        import json
        diff_text = json.dumps(state_diff, ensure_ascii=False, indent=2) if state_diff else "(无变化)"

        prompt = self.prompt_assembler.assemble(PromptInputs(
            role=(
                "你是验证器。基于对象状态变化和执行记录判断目标是否已达成。"
                "输出 JSON: "
                '{"achieved": true/false, "confidence": 0.0-1.0, '
                '"explanation": "简短说明", "unmet": ["未满足的条件"]}'
            ),
            task=(
                f"目标: {goal}\n\n"
                f"对象状态变化:\n{diff_text}\n\n"
                f"执行记录:\n{conversation[-2000:]}"
            ),
        ))
        provider = self._get_provider()
        resp = await retry(provider.complete, prompt, max_tokens=300)
        try:
            text = resp.content.strip()
            if "{" in text and "}" in text:
                text = text[text.find("{"):text.rfind("}") + 1]
            return json.loads(text)
        except json.JSONDecodeError:
            achieved = "YES" in resp.content.upper()
            return {"achieved": achieved, "confidence": 0.3,
                    "explanation": resp.content[:200], "unmet": []}

    def _parse_tool_calls(self, response: str) -> list[dict]:
        """Parse <function_call> tags from LLM response.

        Expected format:
            <function_call>
              <name>tool_name</name>
              <capability>cap_name</capability>
              <parameters>{"key": "value"}</parameters>
            </function_call>

        Handles whitespace variations and optional <parameters>.
        """
        import json
        import re
        results = []

        # Find all function_call blocks — flexible whitespace
        pattern = (
            r"<function_call>\s*"
            r"<name>(.*?)</name>\s*"
            r"<capability>(.*?)</capability>\s*"
            r"(?:<parameters>(.*?)</parameters>\s*)?"
            r"</function_call>"
        )
        for match in re.finditer(pattern, response, re.DOTALL | re.IGNORECASE):
            tool_name = match.group(1).strip()
            cap_name = match.group(2).strip()
            params_str = (match.group(3) or "{}").strip()
            try:
                params = json.loads(params_str)
            except json.JSONDecodeError:
                logger.warning("tool_params_parse_error", params_str=params_str[:100])
                params = {}
            results.append({
                "tool": tool_name,
                "capability": cap_name,
                "params": params,
            })

        if results:
            logger.info("tool_calls_parsed", count=len(results),
                         calls=[f"{r['tool']}.{r['capability']}" for r in results])
        else:
            logger.info("no_tool_calls_in_response", response_preview=response[:200])

        return results

    # ——— Phase 3: Capability recording + Pattern mining ———

    def _record_capability_result(self, task: str, success: bool, steps: int) -> None:
        """Record a completed task result for capability learning."""
        if self._provider_config is None:
            return
        model = self._provider_config.model
        task_type = self._infer_task_type(task)
        self.router.record_result(model, task_type, task, success, steps)
        logger.debug("capability_recorded", model=model, task_type=task_type,
                     success=success)

    @staticmethod
    def _infer_task_type(task: str) -> str:
        """Infer a task type from the task description."""
        task_lower = task.lower()
        if any(kw in task_lower for kw in ("database", "sql", "migrate", "query")):
            return "database"
        if any(kw in task_lower for kw in ("git", "commit", "branch", "push", "merge")):
            return "git"
        if any(kw in task_lower for kw in ("refactor", "rewrite", "restructure")):
            return "refactor"
        if any(kw in task_lower for kw in ("test", "pytest", "coverage")):
            return "testing"
        if any(kw in task_lower for kw in ("deploy", "release", "publish")):
            return "deploy"
        if any(kw in task_lower for kw in ("read", "show", "list", "find", "search")):
            return "read"
        if any(kw in task_lower for kw in ("write", "edit", "create", "add", "modify",
                                            "delete", "remove", "update")):
            return "file_edit"
        return "general"

    # ——— Self-healing tool evolution (九-C + 十-A) ———

    async def _handle_tool_failure(
        self,
        error: Exception,
        tool_name: str,
        capability_name: str,
        params: dict,
        conversation: str,
    ) -> bool:
        """Attempt self-healing on tool failure.

        Returns True if healing was applied (caller should retry).
        """
        from agent.errors import ToolExecutionError, ToolNotFoundError

        if isinstance(error, ToolNotFoundError):
            logger.info("self_heal_missing_capability",
                       tool=tool_name, capability=capability_name)
            prompt = self._build_healing_prompt(
                "missing_capability", tool_name, capability_name, params, conversation
            )
            try:
                resp = await self._get_provider().complete(prompt, max_tokens=2000)
                healing = self._parse_healing_response(resp.content)
            except Exception:
                return False

            if healing.get("action") == "write_helper":
                result = self.tool_editor.add_helper(
                    tool_name=tool_name,
                    helper_name=healing["helper_name"],
                    helper_code=healing["code"],
                    episode_id=self._current_episode_id,
                    reason=healing.get("reason", "Auto-generated: missing capability"),
                )
                if result["success"]:
                    self.registry.reload(tool_name)
                    self.memory.log_evolution_event(
                        result["record_id"], "create", tool_name,
                        self._current_episode_id,
                        f"Auto-heal: added helper {healing['helper_name']}"
                    )
                    return True

        elif isinstance(error, ToolExecutionError):
            # Check if missing verify hook (potential silent failure)
            tool_def = self.registry.get(tool_name)
            cap = self.registry.find_capability(tool_name, capability_name) if tool_def else None
            if cap and not getattr(cap, "verify", None):
                logger.info("self_heal_missing_verify",
                           tool=tool_name, capability=capability_name)
                prompt = self._build_healing_prompt(
                    "missing_verify", tool_name, capability_name, params, conversation
                )
                try:
                    resp = await self._get_provider().complete(prompt, max_tokens=2000)
                    healing = self._parse_healing_response(resp.content)
                except Exception:
                    return False

                if healing.get("action") == "add_verify":
                    result = self.tool_editor.add_verify(
                        tool_name=tool_name,
                        capability_name=capability_name,
                        verify_function=healing["code"],
                        episode_id=self._current_episode_id,
                        reason=healing.get("reason", "Auto-generated: missing verification"),
                    )
                    if result["success"]:
                        self.registry.reload(tool_name)
                        self.memory.log_evolution_event(
                            result["record_id"], "add_verify", tool_name,
                            self._current_episode_id,
                            f"Auto-heal: added verify for {capability_name}"
                        )
                        return True

        return False

    async def _handle_verification_failure(
        self,
        verify_result: VerificationResult,
        tool_name: str,
        capability_name: str,
        params: dict,
        conversation: str,
    ) -> bool:
        """Handle a verification failure. Trigger self-healing to fix the verify hook.

        The verify hook exists but detected a silent failure. The agent can:
        1. Improve the verify function (if it's inaccurate)
        2. Accept and proceed (if verify is too strict)
        """
        logger.warning("verification_failure_handling",
                      tool=tool_name, capability=capability_name)

        prompt = self._build_healing_prompt(
            "fix_verify", tool_name, capability_name, params, conversation,
            extra_context={
                "expected_effect": verify_result.expected_effect,
                "diff": verify_result.diff,
                "suggestion": verify_result.suggestion or "",
            },
        )
        try:
            resp = await self._get_provider().complete(prompt, max_tokens=1000)
            decision = self._parse_healing_response(resp.content)
        except Exception:
            return False

        if decision.get("action") == "fix_verify":
            result = self.tool_editor.add_verify(
                tool_name=tool_name,
                capability_name=capability_name,
                verify_function=decision["code"],
                episode_id=self._current_episode_id,
                reason=decision.get("reason", "Fixed inaccurate verify"),
            )
            if result["success"]:
                self.registry.reload(tool_name)
                self.memory.log_evolution_event(
                    result["record_id"], "modify", tool_name,
                    self._current_episode_id,
                    f"Auto-heal: fixed verify for {capability_name}"
                )
                return True
        elif decision.get("action") == "accept":
            logger.info("verification_accepted_with_warning",
                       tool=tool_name, capability=capability_name)
            return False

        return False

    def _build_healing_prompt(
        self,
        issue_type: str,
        tool_name: str,
        capability_name: str,
        params: dict,
        conversation: str,
        extra_context: dict | None = None,
    ) -> str:
        """Build a prompt for the self-healing LLM call."""
        if issue_type == "missing_capability":
            return self.prompt_assembler.assemble(PromptInputs(
                role=(
                    "你是工具系统修复专家。代理在执行任务时发现缺少一个工具能力。\n"
                    "请编写缺失的工具函数（Python）。\n"
                    '输出 JSON: {"action": "write_helper", "helper_name": "...", '
                    '"code": "...", "reason": "..."}'
                ),
                task=(
                    f"缺失的能力: {tool_name}.{capability_name}\n"
                    f"调用参数: {params}\n"
                    f"最近的对话:\n{conversation[-2000:]}\n\n"
                    f"编写一个 Python 函数来实现这个缺失的能力。"
                    f"参考工具目录中现有代码的风格。"
                ),
            ))
        elif issue_type == "missing_verify":
            return self.prompt_assembler.assemble(PromptInputs(
                role=(
                    "你是验证函数编写专家。代理执行工具后无法确认操作是否真正生效（静默失败风险）。\n"
                    "请为该工具编写一个 verify 函数。\n"
                    '输出 JSON: {"action": "add_verify", "code": "...", "reason": "..."}'
                ),
                task=(
                    f"工具: {tool_name}.{capability_name}\n"
                    f"参数: {params}\n"
                    f"最近的对话:\n{conversation[-2000:]}\n\n"
                    f"编写一个 verify 函数，接收 (params, result) 参数，判断操作是否真的生效。\n"
                    f'函数签名: def verify_{capability_name}(**params, result=None) -> dict\n'
                    f'返回值格式: {{"verified": bool, "expected_effect": str, '
                    f'"actual_state": dict, "expected_state": dict, "suggestion": str or None}}'
                ),
            ))
        elif issue_type == "fix_verify":
            extra = extra_context or {}
            return self.prompt_assembler.assemble(PromptInputs(
                role=(
                    "你是验证函数修复专家。现有的 verify 函数检测到操作可能未生效。\n"
                    "判断 verify 函数是否过于严格（误报），还是确实需要改进。\n"
                    '输出 JSON: {"action": "fix_verify|accept", "code": "...", "reason": "..."}\n'
                    '如果 accept，表示当前验证太严格，接受当前状态。'
                ),
                task=(
                    f"工具: {tool_name}.{capability_name}\n"
                    f"预期效果: {extra.get('expected_effect', '')}\n"
                    f"状态差异: {extra.get('diff', {})}\n"
                    f"建议: {extra.get('suggestion', '')}\n"
                    f"最近对话:\n{conversation[-2000:]}"
                ),
            ))
        return ""

    @staticmethod
    def _parse_healing_response(response: str) -> dict:
        """Parse the JSON response from a self-healing LLM call."""
        import json
        text = response.strip()
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"action": "none", "reason": "Failed to parse LLM response"}

    # ——— Dual-mode exploration/exploitation scheduler (十三-B) ———

    async def _select_mode(self, task_description: str) -> tuple:
        """Classify task as known domain (exploit) or new domain (explore).

        Decision factors:
        1. Matching skills in semantic memory
        2. Similar successful episodes
        3. Explicit user hints
        """
        from enum import Enum as _Enum

        class ExecutionMode(_Enum):
            EXPLORE = "explore"
            EXPLOIT = "exploit"

        mode_info = {
            "mode": ExecutionMode.EXPLORE,
            "confidence": 0.0,
            "matched_skills": [],
            "similar_episodes": [],
            "reason": "",
        }

        # Factor 1: Skill match (semantic memory)
        matching_skills = await self._find_matching_skills(task_description)
        if matching_skills:
            mode_info["matched_skills"] = matching_skills
            mode_info["confidence"] += 0.4

        # Factor 2: Similar episodes
        try:
            similar = self.memory.store.search_semantic(
                task_description[:100], limit=3
            )
            if similar:
                mode_info["similar_episodes"] = [
                    {"summary": s.content[:200], "confidence": s.confidence}
                    for s in similar if s.confidence > 0.5
                ]
                if mode_info["similar_episodes"]:
                    mode_info["confidence"] += 0.3
        except Exception:
            pass

        # Factor 3: Explicit hints
        task_lower = task_description.lower()
        if any(hint in task_lower for hint in ("像上次", "和之前一样", "同样的", "再次", "again", "same as before")):
            mode_info["confidence"] += 0.2

        if mode_info["confidence"] >= 0.5:
            mode_info["mode"] = ExecutionMode.EXPLOIT
            mode_info["reason"] = (
                f"Matched {len(matching_skills)} skills, "
                f"{len(mode_info['similar_episodes'])} similar episodes "
                f"(confidence: {mode_info['confidence']:.0%})"
            )
        else:
            mode_info["mode"] = ExecutionMode.EXPLORE
            mode_info["reason"] = (
                f"No strong matches (confidence: {mode_info['confidence']:.0%})"
            )

        logger.info("mode_selected",
                     mode=mode_info["mode"].value,
                     reason=mode_info["reason"])
        return mode_info["mode"], mode_info

    def _get_provider_for_mode(self, mode) -> Any:
        """Select provider based on execution mode."""
        if not hasattr(self.router, 'providers') or not self.router.providers:
            return self._get_provider()

        if mode.value == "exploit":
            cheapest = self.router.get_cheapest()
            if cheapest:
                return cheapest
        return self.router.get_strongest()

    def _inject_mode_context(self, mode, mode_info: dict) -> str:
        """Build mode-specific context for the prompt."""
        if mode.value == "exploit":
            parts = ["## 已知领域 — 利用模式\n"]
            parts.append("以下是历史上成功完成类似任务的方法，请优先参考：\n")

            for skill in mode_info.get("matched_skills", []):
                parts.append(f"\n### 技能: {skill.get('name', '')}")
                parts.append(f"成功率: {skill.get('success_rate', '?')}%")
                parts.append(f"方法:\n{skill.get('approach', '')}")

            for ep in mode_info.get("similar_episodes", [])[:2]:
                parts.append(f"\n### 历史任务: {ep.get('summary', '')[:200]}")

            return "\n".join(parts)
        else:
            return (
                "## 新领域 — 探索模式\n"
                "这是新的任务类型，没有可直接复用的历史方法。\n"
                "请仔细探索，记录所有尝试过程。"
            )

    async def _find_matching_skills(self, task: str) -> list[dict]:
        """Search semantic memory for matching skills."""
        try:
            results = self.memory.store.search_semantic(
                task[:100], limit=5
            )
            return [
                {
                    "name": r.content[:100] if r.content else "",
                    "success_rate": int(r.confidence * 100),
                    "approach": r.content,
                }
                for r in results
                if r.type in ("skill", "tool_evolution", "pattern")
                and r.confidence > 0.5
            ]
        except Exception:
            return []

    def mine_patterns(self, recent_tasks: int = 100) -> list:
        """Run pattern mining across recent episodes.

        Returns list of PatternProposal for human review.
        """
        if self._pattern_miner is None:
            self._pattern_miner = PatternMiner(self.event_store)
        return self._pattern_miner.mine(recent_tasks=recent_tasks)


# ——— Agent factory ———


def create_agent(
    config: AppConfig | None = None,
    config_path: Path | None = None,
    provider: "LLMProvider | None" = None,
    provider_config: "ProviderConfig | None" = None,
    memory_path: str | None = None,
) -> Agent:
    """Create and set up an Agent instance — the injectable factory.

    Args:
        config: Typed AppConfig (preferred over config_path).
        config_path: Path to config.yaml (legacy, use config= instead).
        provider: Pre-configured LLM provider for testing.
        provider_config: Provider configuration.
        memory_path: Override memory DB path (use ':memory:' for tests).

    Returns:
        A fully set up Agent, ready to run.

    Example:
        # Production
        agent = create_agent(config=AppConfig.from_yaml())

        # Testing
        agent = create_agent(config=AppConfig.test(), memory_path=":memory:")
    """
    if config is None:
        config = AppConfig.from_yaml(config_path)

    # Build config dict BEFORE creating Agent so memory path is correct
    config_dict = {
        "agent": {
            "name": config.agent.name,
            "max_loop_iterations": config.agent.max_loop_iterations,
        },
        "llm": {"providers": config.llm.providers},
        "memory": {"path": memory_path or config.memory.path},
        "tools": {
            "scan_paths": config.tools.scan_paths,
            "default_timeout_ms": config.tools.default_timeout_ms,
        },
        "security": {"dont_do_paths": config.security.dont_do_paths},
    }

    agent = Agent(config_dict=config_dict)

    if provider:
        agent.set_provider(provider, provider_config or ProviderConfig(
            name=provider.name, model=provider.model
        ))

    agent.setup()
    return agent
