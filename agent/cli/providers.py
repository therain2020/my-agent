"""CLI: provider add/list/test/remove. Persisted to disk."""

import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import click

from agent.providers import LLMProvider, ProviderConfig

# Persistence
_STORE_PATH = Path.home() / ".agent-providers.json"


def _load_store() -> dict:
    """Load persisted provider configs."""
    if not _STORE_PATH.exists():
        return {}
    try:
        return json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_store(data: dict) -> None:
    """Persist provider configs to disk."""
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_provider(config: ProviderConfig, adapter: str) -> LLMProvider:
    """Build a provider instance from config. Raises on auth error."""
    if adapter == "anthropic":
        from agent.providers.anthropic import AnthropicProvider
        return AnthropicProvider(config)
    elif adapter == "openai":
        from agent.providers.openai import OpenAIProvider
        return OpenAIProvider(config)
    elif adapter == "deepseek":
        from agent.providers.deepseek import DeepSeekProvider
        return DeepSeekProvider(config)
    elif adapter == "custom":
        from agent.providers.custom import CustomProvider
        return CustomProvider(config)
    raise ValueError(f"Unknown adapter: {adapter}")


_PROVIDER_CACHE: dict[str, LLMProvider] = {}


@click.group(name="provider")
def provider():
    """Manage LLM providers (persisted to ~/.agent-providers.json)."""
    pass


@provider.command()
@click.argument("name")
@click.option("--adapter", type=click.Choice(["anthropic", "openai", "deepseek", "custom"]),
              required=True, help="Provider adapter type")
@click.option("--api-key-env", default="", help="Environment variable for API key")
@click.option("--api-key", default="", help="API key directly (prefer env var)")
@click.option("--model", required=True, help="Model name")
@click.option("--base-url", default="", help="Base URL for custom/openai-compatible")
@click.option("--priority", default="primary",
              type=click.Choice(["primary", "fallback", "last_resort"]))
def add(name: str, adapter: str, api_key_env: str, api_key: str,
        model: str, base_url: str, priority: str) -> None:
    """Add an LLM provider (persisted to disk)."""
    config = ProviderConfig(
        name=name,
        model=model,
        api_key_env=api_key_env,
        api_key=api_key,
        base_url=base_url,
        priority=priority,
    )

    # Validate: can we build the provider?
    try:
        prov = _build_provider(config, adapter)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        return

    # Persist
    store = _load_store()
    store[name] = {
        "adapter": adapter,
        "model": model,
        "api_key_env": api_key_env,
        "api_key": "",
        "base_url": base_url,
        "priority": priority,
    }
    _save_store(store)

    _PROVIDER_CACHE[name] = prov
    click.echo(f"Provider '{name}' added ({adapter}, model={model})")


@provider.command("list")
def list_providers():
    """List configured providers."""
    store = _load_store()
    if not store:
        click.echo("No providers configured. Use 'my-agent provider add' first.")
        click.echo("\nExamples:")
        click.echo("  my-agent provider add qwen --adapter custom \\")
        click.echo("    --api-key-env ALI_TONGYI_KEY \\")
        click.echo("    --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \\")
        click.echo("    --model qwen-plus")
        return
    for name, cfg in store.items():
        click.echo(f"{name:20s} {cfg['model']:30s} {cfg.get('adapter', '?'):12s} {cfg.get('priority', 'primary')}")


@provider.command()
@click.argument("name")
def test(name: str):
    """Test a provider's connectivity."""
    store = _load_store()
    if name not in store:
        click.echo(f"Provider '{name}' not found. Use 'my-agent provider add' first.", err=True)
        return

    cfg_data = store[name]
    config = ProviderConfig(
        name=name,
        model=cfg_data["model"],
        api_key_env=cfg_data.get("api_key_env", ""),
        base_url=cfg_data.get("base_url", ""),
        priority=cfg_data.get("priority", "primary"),
    )
    adapter = cfg_data["adapter"]

    try:
        prov = _build_provider(config, adapter)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        return

    async def _test():
        try:
            resp = await prov.complete("reply with just: ok", max_tokens=10)
            safe_content = resp.content.encode("gbk", errors="replace").decode("gbk")
            click.echo(f"Provider '{name}' OK — model={resp.model}")
            click.echo(f"Response: '{safe_content.strip()}'")
            click.echo(f"Tokens: prompt={resp.prompt_tokens} completion={resp.completion_tokens}")
        except Exception as e:
            click.echo(f"Provider '{name}' FAILED: {e}", err=True)
            import traceback
            trace = traceback.format_exc()
            click.echo(trace.encode("gbk", errors="replace").decode("gbk"), err=True)

    asyncio.run(_test())


@provider.command()
@click.argument("name")
def remove(name: str):
    """Remove a provider."""
    store = _load_store()
    if name not in store:
        click.echo(f"Provider '{name}' not found.", err=True)
        return
    del store[name]
    _save_store(store)
    _PROVIDER_CACHE.pop(name, None)
    click.echo(f"Provider '{name}' removed")


def get_provider(name: str = "") -> Optional[LLMProvider]:
    """Get a provider instance by name (lazy build from persisted config)."""
    store = _load_store()
    if not store:
        return None

    # Pick by name, or first available
    if name and name in store:
        cfg_name = name
    elif not name and store:
        cfg_name = next(iter(store))
    else:
        return None

    # Check cache
    if cfg_name in _PROVIDER_CACHE:
        return _PROVIDER_CACHE[cfg_name]

    # Lazy build
    cfg_data = store[cfg_name]
    config = ProviderConfig(
        name=cfg_name,
        model=cfg_data["model"],
        api_key_env=cfg_data.get("api_key_env", ""),
        base_url=cfg_data.get("base_url", ""),
        priority=cfg_data.get("priority", "primary"),
    )
    try:
        prov = _build_provider(config, cfg_data["adapter"])
        _PROVIDER_CACHE[cfg_name] = prov
        return prov
    except Exception:
        return None


def get_all_providers() -> dict[str, LLMProvider]:
    store = _load_store()
    result = {}
    for name in store:
        p = get_provider(name)
        if p:
            result[name] = p
    return result
