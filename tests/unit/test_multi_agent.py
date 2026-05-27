"""Tests for multi-agent infrastructure."""


from agent.multi_agent import AgentEventBus, AgentPipeline, PipeStage


class TestAgentEventBus:
    async def test_publish_subscribe(self):
        bus = AgentEventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("test.topic", handler)
        await bus.publish("test.topic", {"msg": "hello"}, source="test")

        assert len(received) == 1
        assert received[0].data["msg"] == "hello"
        assert received[0].source == "test"

    async def test_service_call(self):
        bus = AgentEventBus()

        async def handler(data):
            return {"result": f"processed: {data['input']}"}

        bus.register_service("processor", handler)
        result = await bus.call("processor", {"input": "hello"})
        assert result["result"] == "processed: hello"

    async def test_unregistered_service(self):
        bus = AgentEventBus()
        import pytest
        with pytest.raises(ValueError, match="not registered"):
            await bus.call("nonexistent", {})

    async def test_nobody_subscribed_no_error(self):
        bus = AgentEventBus()
        await bus.publish("no.listeners", {})  # Should not raise


class TestAgentPipeline:
    async def test_pipeline_execution(self):
        results = []
        pipeline = AgentPipeline([
            PipeStage(name="stage1", instruction="Process A"),
            PipeStage(name="stage2", instruction="Process B"),
        ])

        async def fake_executor(input_text, stage):
            output = {"name": stage.name, "result": f"output of {stage.name}"}
            results.append(output)
            return output

        await pipeline.run("initial input", fake_executor)
        assert len(results) == 2
        assert results[0]["name"] == "stage1"
        assert results[1]["name"] == "stage2"
