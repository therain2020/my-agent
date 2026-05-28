"""Configuration loading with typed dataclass hierarchy.

Replaces the dict-based config with typed dataclasses for:
- IDE autocomplete and jump-to-definition
- Typo detection at import time (not runtime)
- Environment-specific presets (dev/test)
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .errors import ConfigError

# ——— Config dataclasses ———


@dataclass
class AgentConfig:
    """Agent loop configuration."""
    name: str = "therain2020-agent"
    max_loop_iterations: int = 3
    session_timeout_seconds: int = 300


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    providers: list[dict] = field(default_factory=list)


def _default_data_dir() -> str:
    return str(Path.home() / ".therain2020-agent")


@dataclass
class MemoryConfig:
    """Memory storage configuration."""
    path: str = field(default_factory=lambda: str(Path.home() / ".therain2020-agent" / "memory" / "agent.db"))


@dataclass
class ToolsConfig:
    """Tool registry configuration."""
    scan_paths: list[str] = field(default_factory=lambda: [
        str(Path.home() / ".therain2020-agent" / "tools"),
        str(Path.home() / ".therain2020-agent" / "tools" / ".generated"),
    ])
    default_timeout_ms: int = 30000


@dataclass
class SecurityConfig:
    """Security (dont-do paths) configuration."""
    dont_do_paths: list[str] = field(default_factory=lambda: [
        str(Path.home() / ".therain2020-agent" / "dont-do"),
    ])


@dataclass
class AppConfig:
    """Top-level application configuration."""
    agent: AgentConfig = field(default_factory=AgentConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    # ——— Factory methods ———

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> "AppConfig":
        """Load from YAML file, falling back to defaults."""
        config = cls()

        if path is None:
            path = Path("config.yaml")

        if path.exists():
            with open(path, encoding="utf-8") as f:
                user_data = yaml.safe_load(f) or {}
            config = cls._apply_overrides(config, user_data)

        cls._validate(config)
        return config

    @classmethod
    def dev(cls) -> "AppConfig":
        """Development preset."""
        return cls()

    @classmethod
    def test(cls) -> "AppConfig":
        """Test preset — in-memory DB, short timeouts."""
        return cls(
            agent=AgentConfig(max_loop_iterations=2, session_timeout_seconds=10),
            memory=MemoryConfig(path=":memory:"),
            tools=ToolsConfig(default_timeout_ms=5000),
        )

    @classmethod
    def _apply_overrides(cls, config: "AppConfig", data: dict) -> "AppConfig":
        """Apply dict overrides to config dataclass."""
        if "agent" in data:
            agent_d = data["agent"]
            config.agent = AgentConfig(
                name=agent_d.get("name", config.agent.name),
                max_loop_iterations=agent_d.get("max_loop_iterations", config.agent.max_loop_iterations),
            )
        if "llm" in data:
            config.llm = LLMConfig(providers=data["llm"].get("providers", []))
        if "memory" in data:
            config.memory = MemoryConfig(path=data["memory"].get("path", config.memory.path))
        if "tools" in data:
            tools_d = data["tools"]
            config.tools = ToolsConfig(
                scan_paths=tools_d.get("scan_paths", config.tools.scan_paths),
                default_timeout_ms=tools_d.get("default_timeout_ms", config.tools.default_timeout_ms),
            )
        if "security" in data:
            sec_d = data["security"]
            config.security = SecurityConfig(
                dont_do_paths=sec_d.get("dont_do_paths", config.security.dont_do_paths),
            )
        return config

    @staticmethod
    def _validate(config: "AppConfig") -> None:
        """Validate required fields."""
        if not isinstance(config.llm.providers, list):
            raise ConfigError("llm.providers must be a list")


# ——— Backward-compatible loader ———


def load_config(path: Path | None = None) -> dict:
    """Legacy loader — returns dict for backward compatibility.

    New code should use AppConfig.from_yaml() directly.
    """
    app = AppConfig.from_yaml(path)
    return {
        "agent": {
            "name": app.agent.name,
            "max_loop_iterations": app.agent.max_loop_iterations,
        },
        "llm": {"providers": app.llm.providers},
        "memory": {"path": app.memory.path},
        "tools": {
            "scan_paths": app.tools.scan_paths,
            "default_timeout_ms": app.tools.default_timeout_ms,
        },
        "security": {"dont_do_paths": app.security.dont_do_paths},
    }
