"""Multi-agent collaboration. 类比: D-Bus + Unix pipe.

AgentEventBus: publish/subscribe event system
AgentPipeline: sequential agent chain (| in shell)
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


# === Event Bus (D-Bus model) ===


@dataclass
class AgentEvent:
    topic: str
    data: dict[str, Any]
    source: str = ""


class AgentEventBus:
    """Pub/sub event bus for inter-agent communication. 类比: D-Bus daemon."""

    def __init__(self):
        self._subscribers: dict[str, list[callable]] = {}
        self._services: dict[str, callable] = {}

    def subscribe(self, topic: str, callback: callable):
        """Subscribe to a topic. callback receives AgentEvent."""
        self._subscribers.setdefault(topic, []).append(callback)

    def register_service(self, name: str, handler: callable):
        """Register a named service for point-to-point calls."""
        self._services[name] = handler

    async def publish(self, topic: str, data: dict, source: str = ""):
        """Publish an event to all subscribers. Asynchronous broadcast."""
        event = AgentEvent(topic=topic, data=data, source=source)
        tasks = []
        for cb in self._subscribers.get(topic, []):
            tasks.append(asyncio.create_task(self._safe_invoke(cb, event)))
        if tasks:
            await asyncio.gather(*tasks)
        logger.debug("event_published", topic=topic, subscribers=len(tasks))

    async def call(self, service_name: str, data: dict) -> Any:
        """Point-to-point service call. 类比: D-Bus method call."""
        handler = self._services.get(service_name)
        if not handler:
            raise ValueError(f"Service '{service_name}' not registered")
        return await handler(data)

    async def _safe_invoke(self, callback, event):
        try:
            await callback(event)
        except Exception as e:
            logger.error("event_handler_error", error=str(e)[:200])


# === Pipeline (Unix pipe model) ===


@dataclass
class PipeStage:
    name: str
    instruction: str
    role: str = ""


class AgentPipeline:
    """Sequential agent chain. 类比: Unix pipe (agent_a | agent_b | agent_c)."""

    def __init__(self, stages: list[PipeStage] | None = None):
        self.stages = stages or []

    def add(self, stage: PipeStage):
        self.stages.append(stage)

    async def run(self, initial_input: str,
                  executor: callable) -> list[dict]:
        """Execute pipeline stages sequentially.

        executor: async function (instruction, context) → result dict.
        Each stage gets the previous stage's output as context.
        """
        results = []
        context = initial_input

        for stage in self.stages:
            full_input = f"上游输出:\n{context}\n\n你的任务:\n{stage.instruction}"
            stage_result = await executor(full_input, stage)
            results.append(stage_result)
            context = stage_result.get("result", context)

        return results
