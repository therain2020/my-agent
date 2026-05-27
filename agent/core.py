"""Agent Core — event loop with TODO mode execution. Phase 1."""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog

from .config import load_config
from .consolidation import ConsolidationDaemon
from .correction import (
    Correction,
    correction_to_rule,
    parse_correction_file,
    persist_dont_do_rule,
)
from .dont_do import DontDoEngine, HookPoint, Verdict
from .errors import InterruptSignal
from .interrupt import InterruptHandler
from .memory import EpisodeEntry, EpisodicMemory
from .objects import AgentObject, ObjectState, extract_state_properties
from .prompt import (
    PromptAssembler,
    PromptInputs,
    ToolResultManager,
    format_tool_summary,
)
from .providers import LLMProvider, ProviderConfig
from .retry import retry
from .role import DEFAULT_ROLE
from .security import SecurityManager
from .tools.executor import ToolExecutor
from .tools.registry import ToolRegistry
from .tools.supervisor import ImportedToolSupervisor

logger = structlog.get_logger()


class Agent:
    """Agent core with TODO-mode execution.

    Phase 1: Processes TODO lists step by step.
    Phase 2 will add Goal-mode planning.
    """

    def __init__(self, config_path: Path | None = None):
        self.config = load_config(config_path)
        self.session_id = str(uuid.uuid4())[:8]

        # Components
        self.registry = ToolRegistry(self.config["tools"]["scan_paths"])
        self.supervisor = ImportedToolSupervisor()
        self.executor = ToolExecutor(supervisor=self.supervisor)
        self.security = SecurityManager(self.config["security"]["dont_do_paths"])
        self.memory = EpisodicMemory(self.config["memory"]["path"])
        self.consolidation = ConsolidationDaemon(
            store=self.memory.store,
            provider=self._provider
        )
        self.interrupt = InterruptHandler()
        self.prompt_assembler = PromptAssembler()
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

    def _check_dont_do(self, hook: HookPoint, ctx: dict) -> tuple[Verdict, str]:
        """Check dont-do rules at a hook point. Returns (verdict, message)."""
        verdict, msg = self.dont_do.check(hook, ctx)
        if verdict != Verdict.ALLOW:
            self._track_non_set_change(
                "hit", ctx.get("rule_id", "unknown"),
                msg, ctx
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

    async def _apply_correction(self, correction: Correction) -> None:
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

        # Phase 3: Analyze TODO for clarity and acceptance criteria
        analysis = await self._analyze_todo(task_description)
        acceptance_criteria = analysis.get("acceptance_criteria", [])
        issues = analysis.get("issues", [])
        if issues:
            logger.warning("todo_issues_found", task_id=task_id, issues=len(issues))
            for issue in issues:
                logger.info("todo_issue", type=issue.get("type"),
                            severity=issue.get("severity"),
                            description=issue.get("description", "")[:200])

        conversation = ""
        result_summary = ""
        criteria_text = ""
        if acceptance_criteria:
            criteria_text = (
                "\n\n验收标准（必须全部满足）:\n" +
                "\n".join(f"- {c}" for c in acceptance_criteria)
            )

        for iteration in range(max_iterations):
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
                    result = await self.executor.execute(
                        tool_def, tc["capability"], tc.get("params", {})
                    )
                    tools_used.append(f"{tc['tool']}.{tc['capability']}")
                    steps_taken += 1

                    result_str = str(result)[:2000]
                    conversation += f"\n[Result from {tc['tool']}.{tc['capability']}]: {result_str}"

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
        conversation = ""

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

                # Phase 2: Analyze + Plan
                plan = await self._plan_goal(goal, observation, conversation)
                if not plan:
                    last_error = "LLM did not produce a plan"
                    break
                # PLAN hook: filter steps that violate dont-do rules
                plan = self._filter_plan_by_dont_do(plan)
                if not plan:
                    last_error = "All plan steps rejected by dont-do rules"
                    break
                conversation += f"\n[Plan] {len(plan)} steps generated"
            else:
                # Retry: check for user corrections, then replan
                corrections = await self._check_for_corrections()
                for corr in corrections:
                    await self._apply_correction(corr)

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

                        result = await self.executor.execute(
                            tool_def, tc["capability"], tc.get("params", {})
                        )
                        tools_used.append(f"{tc['tool']}.{tc['capability']}")
                        steps_taken += 1
                        result_str = str(result)[:500]
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

            # Phase 4 V2: Structured Verify
            verification = await self._verify_goal(goal, conversation)
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

        # Record episode
        success = not last_error
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

        prompt = self.prompt_assembler.assemble(PromptInputs(
            role=(
                "基于观察结果，使用可用工具为目标制定执行计划。"
                "输出 JSON 格式的计划数组，每步包含 action, tool, object 和 verify。"
                "如果不可自动验证，设置 verify: 'manual'。"
                "不要在 JSON 之外输出任何内容。"
            ),
            tool_summaries=format_tool_summary(relevant_tools),
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
