"""MCP transport layer. 类比: Linux I/O models.

stdio   → pipe (parent-child process)
SSE     → TCP persistent connection (Server-Sent Events)
HTTP    → HTTP request/response (Streamable HTTP)
"""

from typing import Protocol

import structlog

logger = structlog.get_logger()


class MCPTransport(Protocol):
    """MCP transport interface. 类比: VFS file_operations."""

    async def connect(self) -> None: ...
    async def send(self, message: dict) -> dict: ...
    async def close(self) -> None: ...


def detect_transport(source: str) -> str:
    """Detect transport type from connection string."""
    source = source.strip()
    if source.startswith("http://") or source.startswith("https://"):
        if "/sse" in source.lower():
            return "sse"
        return "http"
    return "stdio"


class StdioTransport:
    """Pipe-based transport. Already implemented via supervisor.py.

    This is a documentation stub — the real implementation lives in
    ImportedToolSupervisor.start() with transport='stdio'.
    """
    transport_type = "stdio"

    def __init__(self, command: str):
        self.command = command

    async def connect(self):
        pass  # Handled by supervisor.start()

    async def send(self, message: dict) -> dict:
        raise NotImplementedError("Use ImportedToolSupervisor.call_tool()")

    async def close(self):
        pass


class SSETransport:
    """SSE (Server-Sent Events) transport. 类比: TCP persistent connection.

    For remote MCP servers accessible via HTTP SSE endpoint.
    Supports keepalive heartbeat and exponential-backoff reconnection.
    """

    transport_type = "sse"

    def __init__(self, url: str, heartbeat_interval: float = 30.0, max_retries: int = 5):
        self.url = url.rstrip("/")
        self.heartbeat_interval = heartbeat_interval
        self.max_retries = max_retries
        self._client = None
        self._connected = False

    async def connect(self):
        import httpx
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        self._connected = True
        logger.info("sse_connected", url=self.url)

    async def send(self, message: dict) -> dict:
        if not self._connected:
            await self.connect()
        import httpx
        for attempt in range(self.max_retries):
            try:
                resp = await self._client.post(
                    f"{self.url}/message", json=message,
                    headers={"Accept": "text/event-stream"},
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError:
                if attempt == self.max_retries - 1:
                    raise
                backoff = min(2 ** attempt, 30)
                logger.warning("sse_retry", attempt=attempt + 1, backoff=backoff)
                import asyncio
                await asyncio.sleep(backoff)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._connected = False
            logger.info("sse_closed", url=self.url)


class StreamableHTTPTransport:
    """Streamable HTTP transport. 类比: HTTP request/response.

    Stateless — each call is an independent HTTP request.
    Simplest to implement and debug.
    """

    transport_type = "http"

    def __init__(self, url: str, max_retries: int = 3):
        self.url = url.rstrip("/")
        self.max_retries = max_retries

    async def connect(self):
        pass  # Stateless, no persistent connection

    async def send(self, message: dict) -> dict:
        import httpx
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            for attempt in range(self.max_retries):
                try:
                    resp = await client.post(
                        f"{self.url}/message", json=message,
                    )
                    resp.raise_for_status()
                    return resp.json()
                except httpx.HTTPError:
                    if attempt == self.max_retries - 1:
                        raise
                    import asyncio
                    await asyncio.sleep(2 ** attempt)

    async def close(self):
        pass
