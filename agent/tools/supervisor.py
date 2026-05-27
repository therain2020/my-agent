"""MCP tool process supervisor. 类比: systemd service supervision."""

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger()


class ImportedToolSupervisor:
    """Manages lifecycle of imported MCP server processes.

    类比: systemd — starts, monitors, and restarts services.
    Each MCP server runs as a subprocess. If it crashes, we restart it
    (Restart=on-failure). On shutdown, we send SIGTERM then SIGKILL.
    """

    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._mcp_clients: dict[str, Any] = {}  # MCP client instances
        self._watchdog_tasks: dict[str, asyncio.Task] = {}

    async def start(self, name: str, command: str, transport: str = "stdio") -> None:
        """Start an MCP server process. 类比: systemctl start <service>."""
        if name in self._processes:
            await self.stop(name)

        from mcp import Client
        from mcp.client.stdio import stdio_client

        if transport == "stdio":
            cmd_parts = command.split()
            server_params = {
                "command": cmd_parts[0],
                "args": cmd_parts[1:] if len(cmd_parts) > 1 else [],
            }
            stdio_transport = await stdio_client(server_params)
            client = Client(stdio_transport[0], stdio_transport[1])
        else:
            from agent.errors import ImportError_
            raise ImportError_(f"MCP transport '{transport}' not yet supported")

        self._mcp_clients[name] = client
        logger.info("mcp_server_started", name=name, command=command)

        # Start watchdog
        self._watchdog_tasks[name] = asyncio.create_task(
            self._watch(name, command, transport)
        )

    async def stop(self, name: str) -> None:
        """Stop an MCP server. 类比: systemctl stop <service>."""
        if name in self._watchdog_tasks:
            self._watchdog_tasks[name].cancel()
            del self._watchdog_tasks[name]

        proc = self._processes.pop(name, None)
        client = self._mcp_clients.pop(name, None)

        if client:
            try:
                await client.close()
            except Exception:
                pass

        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

        logger.info("mcp_server_stopped", name=name)

    async def call_tool(
        self, server_name: str, tool_name: str, params: dict, timeout_ms: int = 30000
    ) -> Any:
        """Call a tool on an MCP server. 类比: D-Bus method call."""
        client = self._mcp_clients.get(server_name)
        if not client:
            from agent.errors import ToolError
            raise ToolError(f"MCP server '{server_name}' not running. Use 'my-agent tools list' to check status.")

        result = await client.call_tool(tool_name, params)
        return result

    def is_running(self, name: str) -> bool:
        """Check if an MCP server is running."""
        return name in self._mcp_clients

    def list_running(self) -> list[str]:
        """List all running MCP servers."""
        return list(self._mcp_clients.keys())

    async def shutdown_all(self) -> None:
        """Stop all MCP servers. 类比: systemctl stop on shutdown."""
        for name in list(self._mcp_clients.keys()):
            await self.stop(name)

    async def _watch(self, name: str, command: str, transport: str) -> None:
        """Watchdog: restart MCP server if it crashes. 类比: Restart=on-failure."""
        while True:
            await asyncio.sleep(5)
            if name not in self._mcp_clients:
                return  # Stopped intentionally

            client = self._mcp_clients.get(name)
            if client is None:
                logger.warning("mcp_server_crashed", name=name, action="restarting")
                try:
                    await self.start(name, command, transport)
                except Exception as e:
                    logger.error("mcp_server_restart_failed", name=name, error=str(e))
