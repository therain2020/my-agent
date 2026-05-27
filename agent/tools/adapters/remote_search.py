"""Remote search for importable tools. 类比: apt search + apt-cache.

Searches GitHub (SKILL.md repos, MCP servers) and MCP Registry.
"""

import asyncio
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class SearchResult:
    name: str
    source: str          # "github" | "mcp-registry" | "local"
    description: str = ""
    url: str = ""
    type: str = ""       # "skill" | "mcp" | "plugin"
    stars: int = 0
    install_command: str = ""


class RemoteSearchAggregator:
    """Aggregated search across multiple sources. 类比: apt + multiple sources.list."""

    def __init__(self):
        self._sources = [
            GitHubSearchSource(),
            MCPRegistrySource(),
        ]

    async def search(self, keyword: str, limit: int = 20) -> list[SearchResult]:
        tasks = [s.search(keyword) for s in self._sources]
        all_results = []
        for coro in asyncio.as_completed(tasks):
            try:
                all_results.extend(await coro)
            except Exception as e:
                logger.warning("search_source_error", error=str(e)[:200])
        return all_results[:limit]


class GitHubSearchSource:
    """Search GitHub for importable MCP servers and skills."""

    source_name = "github"

    async def search(self, keyword: str) -> list[SearchResult]:
        results = []

        # Search for MCP servers
        results.extend(await self._search_mcp(keyword))

        # Search for Claude Code skills
        results.extend(await self._search_skills(keyword))

        return results

    async def _search_mcp(self, keyword: str) -> list[SearchResult]:
        """Search for MCP server repos on GitHub."""
        results = []
        queries = [
            f"{keyword} topic:mcp-server",
            f"{keyword} mcp-server in:name",
        ]
        for query in queries[:1]:  # Just one query to keep it fast
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(
                        "https://api.github.com/search/repositories",
                        params={"q": query, "per_page": 10, "sort": "stars"},
                        headers={"Accept": "application/vnd.github+json"},
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for repo in data.get("items", []):
                        results.append(SearchResult(
                            name=repo["full_name"],
                            source="github",
                            description=repo.get("description", ""),
                            url=repo["html_url"],
                            type="mcp",
                            stars=repo.get("stargazers_count", 0),
                            install_command=(
                                f"therain2020-agent add mcp "
                                f"\"npx @{repo['full_name'].lower()}\""
                            ),
                        ))
            except Exception:
                continue
        return results

    async def _search_skills(self, keyword: str) -> list[SearchResult]:
        """Search for Claude Code SKILL.md repos."""
        results = []
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://api.github.com/search/code",
                    params={
                        "q": f"{keyword} filename:SKILL.md",
                        "per_page": 10,
                    },
                    headers={"Accept": "application/vnd.github+json"},
                )
                if resp.status_code != 200:
                    return results
                data = resp.json()
                for item in data.get("items", []):
                    repo_name = item["repository"]["full_name"]
                    results.append(SearchResult(
                        name=f"{repo_name}/SKILL.md",
                        source="github",
                        description=f"Skill from {repo_name}",
                        url=item["html_url"],
                        type="skill",
                        stars=item["repository"].get("stargazers_count", 0),
                        install_command=f"therain2020-agent add skill (clone from {repo_name})",
                    ))
        except Exception:
            pass
        return results


class MCPRegistrySource:
    """Search the MCP Registry for servers."""

    source_name = "mcp-registry"
    base_url = "https://registry.modelcontextprotocol.io"

    async def search(self, keyword: str) -> list[SearchResult]:
        results = []
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/api/servers",
                    params={"q": keyword},
                )
                if resp.status_code != 200:
                    return results
                data = resp.json()
                for server in data.get("servers", [])[:10]:
                    results.append(SearchResult(
                        name=server.get("name", ""),
                        source="mcp-registry",
                        description=server.get("description", ""),
                        url=server.get("homepage", ""),
                        type="mcp",
                        install_command=server.get("install_command", ""),
                    ))
        except Exception:
            pass
        return results
