"""Configuration loading and validation."""

from pathlib import Path

import yaml

from .errors import ConfigError

DEFAULT_CONFIG = {
    "agent": {
        "name": "my-agent",
        "max_loop_iterations": 3,
    },
    "llm": {
        "providers": [],
    },
    "memory": {
        "path": "./memory",
    },
    "tools": {
        "scan_paths": ["./tools", "./tools/.generated"],
        "default_timeout_ms": 30000,
    },
    "security": {
        "dont_do_paths": ["./dont-do"],
    },
}


def load_config(path: Path | None = None) -> dict:
    """Load and validate config.yaml, merging with defaults.

    If no path is given, looks for config.yaml in the current directory.
    """
    if path is None:
        path = Path("config.yaml")

    config = _deep_merge(DEFAULT_CONFIG, {})

    if path.exists():
        with open(path, encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)
    else:
        import structlog
        logger = structlog.get_logger()
        logger.info("config_file_not_found", path=str(path),
                     message="Using default config")

    _validate(config)
    return config


def _validate(config: dict) -> None:
    """Validate required fields."""
    if "llm" not in config:
        raise ConfigError("Missing 'llm' section in config")
    _providers = config["llm"].get("providers", [])
    # Providers can also be added via CLI, so empty is OK on load


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts. override values win."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
