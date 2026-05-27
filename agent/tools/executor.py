"""Tool executor. Supports import and mcp runtimes."""

import asyncio
import importlib
import importlib.util
import inspect
from pathlib import Path
from typing import Any

import structlog

from .loader import ToolDefinition

logger = structlog.get_logger()


class ToolExecutor:
    """Execute tool capabilities. 类比: execve + kernel module call."""

    # Maps runtime types to their execution methods
    RUNTIME_IMPORT = "import"
    RUNTIME_MCP = "mcp"
    RUNTIME_SUBPROCESS = "subprocess"

    def __init__(self, supervisor=None):
        self._supervisor = supervisor  # ImportedToolSupervisor for MCP runtime

    async def execute(
        self,
        tool_def: ToolDefinition,
        capability_name: str,
        params: dict[str, Any],
        timeout_ms: int | None = None,
    ) -> Any:
        """Execute a capability on a tool.

        Routes to the correct runtime based on tool_def.runtime.
        """
        cap = None
        for c in tool_def.capabilities:
            if c.name == capability_name:
                cap = c
                break

        if cap is None:
            from agent.errors import ToolNotFoundError
            raise ToolNotFoundError(
                f"Capability '{capability_name}' not found on tool '{tool_def.name}'"
            )

        timeout = timeout_ms or cap.timeout_ms

        if tool_def.runtime == self.RUNTIME_IMPORT:
            return await self._execute_import(tool_def, cap, params, timeout)
        elif tool_def.runtime == self.RUNTIME_MCP:
            return await self._execute_mcp(tool_def, cap, params, timeout)
        elif tool_def.runtime == self.RUNTIME_SUBPROCESS:
            return await self._execute_subprocess(tool_def, cap, params, timeout)
        else:
            from agent.errors import ToolError
            raise ToolError(f"Unknown runtime: {tool_def.runtime}")

    async def _execute_import(
        self, tool_def: ToolDefinition, cap: Any, params: dict, timeout_ms: int
    ) -> Any:
        """Execute via Python import. 类比: 内核模块调用."""
        entry = tool_def.entry_points.get(cap.name)
        if not entry:
            from agent.errors import ToolError
            raise ToolError(
                f"No entry_point for '{cap.name}' on '{tool_def.name}'"
            )

        # entry format: "module.py:function_name"
        if ":" not in entry:
            from agent.errors import ToolError
            raise ToolError(f"Invalid entry_point '{entry}', expected 'file:function'")

        module_path, func_name = entry.split(":", 1)

        # Resolve relative to tool_dir
        if tool_def.tool_dir:
            script_path = tool_def.tool_dir / module_path
        else:
            script_path = Path(module_path)

        if not script_path.exists():
            from agent.errors import ToolError
            raise ToolError(f"Entry point file not found: {script_path}")

        # Dynamic import
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            f"tool_{tool_def.name}_{cap.name}", str(script_path)
        )
        if spec is None:
            from agent.errors import ToolError
            raise ToolError(f"Cannot load module spec for: {script_path}")

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        func = getattr(mod, func_name)

        try:
            if inspect.iscoroutinefunction(func):
                result = await asyncio.wait_for(func(**params), timeout=timeout_ms / 1000)
            else:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, lambda: func(**params)),
                    timeout=timeout_ms / 1000,
                )
            return result
        except asyncio.TimeoutError:
            from agent.errors import ToolTimeoutError
            raise ToolTimeoutError(tool_def.name, timeout_ms / 1000)
        except Exception as e:
            from agent.errors import ToolExecutionError
            raise ToolExecutionError(tool_def.name, -1, str(e))
            raise ToolExecutionError(tool_def.name, -1, str(e))

    async def _execute_mcp(
        self, tool_def: ToolDefinition, cap: Any, params: dict, timeout_ms: int
    ) -> Any:
        """Execute via MCP JSON-RPC. 类比: RPC call."""
        if self._supervisor is None:
            from agent.errors import ToolError
            raise ToolError("MCP supervisor not configured")

        return await self._supervisor.call_tool(
            tool_def.name, cap.name, params, timeout_ms
        )

    async def _execute_subprocess(
        self, tool_def: ToolDefinition, cap: Any, params: dict, timeout_ms: int
    ) -> Any:
        """Execute via subprocess. 类比: fork + execve."""
        import json
        import sys

        entry = tool_def.entry_points.get(cap.name)
        if not entry:
            from agent.errors import ToolError
            raise ToolError(f"No entry_point for '{cap.name}'")

        script_path = tool_def.tool_dir / entry if tool_def.tool_dir else Path(entry)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(script_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=json.dumps(params).encode()),
                timeout=timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            proc.kill()
            from agent.errors import ToolTimeoutError
            raise ToolTimeoutError(tool_def.name, timeout_ms / 1000)

        if proc.returncode != 0:
            from agent.errors import ToolExecutionError
            raise ToolExecutionError(tool_def.name, proc.returncode, stderr.decode())

        return json.loads(stdout)
