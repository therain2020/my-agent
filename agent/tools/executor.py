"""Tool executor. Supports import and mcp runtimes. Phase 2 — verify hooks."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from .loader import ToolDefinition

logger = structlog.get_logger()


@dataclass
class VerificationResult:
    """Result of a post-action verification hook. 类比: fsck after write."""

    verified: bool
    expected_effect: str = ""
    actual_state: dict = field(default_factory=dict)
    expected_state: dict = field(default_factory=dict)
    suggestion: str | None = None

    @property
    def diff(self) -> dict:
        """Compute the difference between expected and actual state."""
        diffs = {}
        all_keys = set(self.expected_state.keys()) | set(self.actual_state.keys())
        for k in all_keys:
            expected = self.expected_state.get(k)
            actual = self.actual_state.get(k)
            if expected != actual:
                diffs[k] = {"expected": expected, "actual": actual}
        return diffs


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
        except TimeoutError:
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
        except TimeoutError:
            proc.kill()
            from agent.errors import ToolTimeoutError
            raise ToolTimeoutError(tool_def.name, timeout_ms / 1000)

        if proc.returncode != 0:
            from agent.errors import ToolExecutionError
            raise ToolExecutionError(tool_def.name, proc.returncode, stderr.decode())

        return json.loads(stdout)

    # === Verification hooks (十-A: silent failure detection) ===

    async def execute_and_verify(
        self,
        tool_def: ToolDefinition,
        capability_name: str,
        params: dict[str, Any],
        timeout_ms: int | None = None,
    ) -> tuple[Any, VerificationResult | None]:
        """Execute and verify in one step. 类比: write + fsck.

        If the capability has a verify hook configured, runs it after execution.
        Returns (result, verification) — verification is None if no hook defined.
        """
        result = await self.execute(tool_def, capability_name, params, timeout_ms)

        cap = self._find_capability(tool_def, capability_name)
        if cap is None:
            return result, None

        verify_config = getattr(cap, "verify", None)
        if verify_config is None:
            return result, None

        try:
            verify_result = await self._run_verify(
                tool_def, verify_config, params, result
            )
            if not verify_result.verified:
                logger.warning(
                    "verification_failed",
                    tool=tool_def.name,
                    capability=capability_name,
                    diff=verify_result.diff,
                )
            return result, verify_result
        except Exception as e:
            logger.warning(
                "verify_execution_failed",
                tool=tool_def.name,
                capability=capability_name,
                error=str(e),
            )
            return result, VerificationResult(
                verified=False,
                expected_effect="(verify function failed to execute)",
                actual_state={"error": str(e)},
                suggestion="Verify function needs to be fixed or rewritten",
            )

    async def _run_verify(
        self,
        tool_def: ToolDefinition,
        verify_config: dict,
        params: dict[str, Any],
        result: Any,
    ) -> VerificationResult:
        """Execute the verify function for a capability.

        The verify function receives the original params and the execution result,
        and returns a dict with keys: verified, expected_effect, actual_state,
        expected_state, suggestion.
        """
        verify_entry = verify_config.get("function", "")
        if ":" not in verify_entry:
            return VerificationResult(
                verified=False,
                expected_effect="(invalid verify config)",
                suggestion=f"Verify entry '{verify_entry}' is not in 'file:function' format",
            )

        module_path, func_name = verify_entry.split(":", 1)

        if tool_def.tool_dir:
            script_path = tool_def.tool_dir / module_path
        else:
            script_path = Path(module_path)

        if not script_path.exists():
            return VerificationResult(
                verified=False,
                expected_effect="(verify script not found)",
                actual_state={"missing_file": str(script_path)},
                suggestion=f"Verify script {module_path} not found — regen required",
            )

        spec = importlib.util.spec_from_file_location(
            f"verify_{tool_def.name}_{func_name}", str(script_path)
        )
        if spec is None or spec.loader is None:
            return VerificationResult(
                verified=False,
                expected_effect="(cannot load verify module)",
                suggestion="Verify module cannot be loaded",
            )

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        verify_func = getattr(mod, func_name, None)

        if verify_func is None:
            return VerificationResult(
                verified=False,
                expected_effect=f"(verify function {func_name} not found in {module_path})",
                suggestion="Verify function name may be incorrect",
            )

        try:
            raw = verify_func(**params, result=result)
            return VerificationResult(
                verified=raw.get("verified", False),
                expected_effect=raw.get("expected_effect", ""),
                actual_state=raw.get("actual_state", {}),
                expected_state=raw.get("expected_state", {}),
                suggestion=raw.get("suggestion"),
            )
        except Exception as e:
            return VerificationResult(
                verified=False,
                expected_effect="(verify function raised exception)",
                actual_state={"exception": str(e)},
                suggestion="Verify function has a bug and needs to be fixed",
            )

    @staticmethod
    def _find_capability(tool_def: ToolDefinition, cap_name: str):
        """Find a capability by name on a tool definition."""
        for c in tool_def.capabilities:
            if c.name == cap_name:
                return c
        return None
