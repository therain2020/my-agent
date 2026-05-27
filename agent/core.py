"""Agent Core — event loop with TODO mode execution. Phase 1."""

import asyncio
import time
import uuid
from pathlib import Path

import structlog

from .config import load_config
from .consolidation import ConsolidationDaemon
from .errors import InterruptSignal
from .interrupt import InterruptHandler
from .memory import EpisodeEntry, EpisodicMemory
from .prompt import (
    PromptAssembler,
    PromptInputs,
    ToolResultManager,
    format_tool_summary,
)
from .providers import LLMProvider, ProviderConfig
from .retry import retry
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

        # LLM Provider (lazy)
        self._provider: LLMProvider | None = None
        self._provider_config: ProviderConfig | None = None

    def set_provider(self, provider: LLMProvider, config: ProviderConfig) -> None:
        """Set the LLM provider."""
        self._provider = provider
        self._provider_config = config
        logger.info("provider_set", name=provider.name, model=provider.model)

    def setup(self) -> None:
        """Initialize all subsystems."""
        self.registry.scan()
        self.security.load_rules()
        self.interrupt.setup()
        logger.info("agent_setup",
                     session=self.session_id,
                     tools=len(self.registry.list_all()),
                     dont_do_rules=len(self.security.list_rules()))

    def teardown(self) -> None:
        """Clean up all subsystems."""
        self.interrupt.teardown()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.supervisor.shutdown_all())
        except RuntimeError:
            # No running event loop, skip async cleanup
            pass

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

        conversation = ""
        result_summary = ""

        for iteration in range(max_iterations):
            await self.interrupt.check()

            # Build prompt
            tools = self.registry.list_all()
            relevant_objects = list(set(
                obj for t in tools for obj in t.objects
            ))

            role_text = (
                "你是一个编程助手。按照用户的任务指令逐步执行。\n\n"
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
                task=task_description,
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
                try:
                    tool_def = self.registry.get(tc["tool"])
                    if not tool_def:
                        conversation += f"\n[Error] 未找到工具: {tc['tool']}"
                        continue

                    result = await self.executor.execute(
                        tool_def, tc["capability"], tc.get("params", {})
                    )
                    tools_used.append(f"{tc['tool']}.{tc['capability']}")
                    steps_taken += 1

                    result_str = str(result)[:2000]
                    conversation += f"\n[Result from {tc['tool']}.{tc['capability']}]: {result_str}"

                except InterruptSignal:
                    raise
                except Exception as e:
                    last_error = str(e)
                    conversation += f"\n[Error] {tc['tool']}.{tc['capability']}: {e}"

        # Record episode
        success = not last_error
        self.memory.log_episode(EpisodeEntry(
            task_id=task_id,
            task_type="todo",
            task_summary=task_description[:200],
            tools_used=list(set(tools_used)),
            steps=steps_taken,
            success=success,
            error=last_error,
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
                # Phase 1: Observe — understand current state
                observation = await self._observe(goal, conversation)
                conversation += f"\n[Observe] {observation[:500]}"

                # Phase 2: Analyze + Plan
                plan = await self._plan_goal(goal, observation, conversation)
                if not plan:
                    last_error = "LLM did not produce a plan"
                    break
                conversation += f"\n[Plan] {len(plan)} steps generated"
            else:
                # Retry: replan with what we've learned
                plan = await self._plan_goal(
                    goal, f"Previous attempt failed. {conversation[-2000:]}", conversation
                )
                if not plan:
                    break

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
                        if tool_def:
                            result = await self.executor.execute(
                                tool_def, tc["capability"], tc.get("params", {})
                            )
                            tools_used.append(f"{tc['tool']}.{tc['capability']}")
                            steps_taken += 1
                            conversation += (
                                f"\n[Result from {tc['tool']}.{tc['capability']}]: "
                                f"{str(result)[:500]}"
                            )
                except InterruptSignal:
                    raise
                except Exception as e:
                    conversation += f"\n[Error] {step.get('action', str(step))[:100]}: {e}"

            # Phase 4: Verify
            verified = await self._verify_goal(goal, conversation)
            if verified:
                last_error = ""
                break
            last_error = "Goal not verified after execution"

        # Record episode
        success = not last_error
        self.memory.log_episode(EpisodeEntry(
            task_id=task_id, task_type="goal", task_summary=goal[:200],
            tools_used=list(set(tools_used)), steps=steps_taken,
            success=success, error=last_error,
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

    async def _observe(self, goal: str, conversation: str) -> str:
        """Phase 1: Observe current state relevant to the goal."""
        tools = self.registry.list_all()
        prompt = self.prompt_assembler.assemble(PromptInputs(
            role=(
                "你需要了解当前状态以完成目标。"
                "用 function_call 格式调用工具来观察现状。"
                "完成观察后输出 <final>done</final>。"
            ),
            tool_summaries=format_tool_summary(tools),
            task=f"目标: {goal}\n\n先观察当前状态，再制定计划。",
        ))
        provider = self._get_provider()
        resp = await retry(provider.complete, prompt, max_tokens=4096)
        tool_calls = self._parse_tool_calls(resp.content)
        observations = []
        for tc in tool_calls:
            tool_def = self.registry.get(tc["tool"])
            if tool_def:
                result = await self.executor.execute(
                    tool_def, tc["capability"], tc.get("params", {})
                )
                observations.append(f"[{tc['tool']}.{tc['capability']}]: {str(result)[:500]}")
        return "\n".join(observations) if observations else resp.content[:1000]

    async def _plan_goal(self, goal: str, observation: str, conversation: str) -> list[dict]:
        """Phase 2+3: Analyze gap and generate plan."""
        prompt = self.prompt_assembler.assemble(PromptInputs(
            role=(
                "基于观察结果，为目标制定执行计划。"
                "输出 JSON 格式的计划数组，每步包含 action 和 verify。"
                "如果不可自动验证，设置 verify: 'manual'。"
                "不要在 JSON 之外输出任何内容。"
            ),
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
            # If LLM didn't output JSON, treat response as a single step
            return [{"action": resp.content[:500], "verify": "manual"}]

    async def _verify_goal(self, goal: str, conversation: str) -> bool:
        """Phase 5: Verify if the goal is achieved."""
        prompt = self.prompt_assembler.assemble(PromptInputs(
            role="根据执行结果判断目标是否已达成。只回复 YES 或 NO。",
            task=f"目标: {goal}\n\n执行结果:\n{conversation[-3000:]}",
        ))
        provider = self._get_provider()
        resp = await retry(provider.complete, prompt, max_tokens=16)
        return "YES" in resp.content.upper()

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
