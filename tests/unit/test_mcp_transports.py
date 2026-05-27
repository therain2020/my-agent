"""Tests for MCP transport detection and types."""

from agent.tools.mcp_transports import (
    SSETransport,
    StreamableHTTPTransport,
    detect_transport,
)


class TestTransportDetection:
    def test_detect_stdio(self):
        assert detect_transport("npx @anthropic/mcp-server-git") == "stdio"
        assert detect_transport("python server.py") == "stdio"

    def test_detect_sse(self):
        assert detect_transport("https://example.com/sse") == "sse"
        assert detect_transport("http://localhost:8080/SSE") == "sse"

    def test_detect_http(self):
        assert detect_transport("https://api.example.com/mcp") == "http"
        assert detect_transport("http://localhost:9999") == "http"


class TestTransportClasses:
    def test_sse_transport_init(self):
        t = SSETransport("https://example.com/sse")
        assert t.transport_type == "sse"
        assert t.url == "https://example.com/sse"

    def test_http_transport_init(self):
        t = StreamableHTTPTransport("https://api.example.com/mcp")
        assert t.transport_type == "http"
        assert t.url == "https://api.example.com/mcp"
