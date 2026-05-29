"""Interactive provider setup wizard — `therain2020 --setup`."""

from __future__ import annotations

from .config import PROVIDER_REGISTRY, load_config, save_config


def run_setup():
    """Configure an LLM provider. Saves to ~/.therain2020-agent/config.yaml."""

    print()
    print("  === therain2020 Setup ===")
    print()
    print("  Configure your LLM provider. Your API key is saved to:")
    print("  ~/.therain2020-agent/config.yaml")
    print("  (env vars take priority over the config file)")
    print()

    # ---- Phase 1: pick provider ----
    print("  Providers:")
    print()
    print("  —— International ——")
    _show_provider_group(["openai", "openai-l", "anthropic", "anthropic-l",
                          "gemini", "groq", "mistral", "together",
                          "cerebras", "xai", "cohere", "perplexity",
                          "fireworks", "replicate"])
    print()
    print("  —— 国内 ——")
    _show_provider_group(["deepseek", "qwen", "qwen-l", "zhipu", "zhipu-l",
                          "moonshot", "doubao", "doubao-l", "baichuan",
                          "minimax", "yi", "spark", "ernie"])
    print()
    print("  —— Other ——")
    print("  [C] Custom OpenAI-compatible endpoint")
    print()

    choice = input(f"  Pick provider (name or number 1-{len(PROVIDER_REGISTRY)}"
                   f", or C for custom): ").strip()

    provider_key = None
    if choice.upper() == "C":
        provider_key = "custom"
    elif choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(PROVIDER_REGISTRY):
            provider_key = PROVIDER_REGISTRY[idx][0]
    else:
        # match by name
        for key, label, _, _, _, _ in PROVIDER_REGISTRY:
            if key == choice.lower() or label.lower() == choice.lower():
                provider_key = key
                break

    if provider_key is None:
        print(f"  Unknown provider: {choice}")
        return

    label, env_var, default_model, default_base, cost = _find_provider(provider_key)
    print()

    config = load_config()

    # ---- Phase 2: env var name (user-specified) ----
    if env_var:
        env_val = _env_has(env_var)
        if env_val:
            print(f"  {_check()} Detected {env_var} from environment ({_mask(env_val)})")
            api_key = env_val
            env_var_name = env_var
        else:
            print(f"  Default env var: {env_var}")
            custom_env = input(
                f"  Env var name (Enter to use {env_var}, "
                f"or type your own): "
            ).strip()
            env_var_name = custom_env if custom_env else env_var
            api_key = _env_has(env_var_name)
            if api_key:
                print(f"  {_check()} Found in {env_var_name}")
            else:
                api_key = _prompt_secret(f"  API key for {label}: ")
    else:
        # Custom or provider without default env var
        env_var_name = input(
            "  Env var name for API key (e.g. MY_API_KEY): "
        ).strip()
        if env_var_name:
            api_key = _env_has(env_var_name)
            if api_key:
                print(f"  {_check()} Found in {env_var_name}")
            else:
                api_key = _prompt_secret(f"  API key for {label}: ")
        else:
            api_key = _prompt_secret(f"  API key for {label} (or blank for none): ")

    if api_key:
        _save_key(config, provider_key, api_key, env_var_name)

    print()

    # ---- Phase 3: model override ----
    print(f"  Default model: {default_model}")
    model = input("  Override (or Enter to keep default): ").strip()
    if model:
        config["providers"].setdefault(provider_key, {})["model"] = model
        print(f"  {_check()} Model: {model}")

    # ---- Phase 4: base URL override ----
    if default_base:
        print(f"  Endpoint: {default_base}")
        base = input("  Override (or Enter to keep default): ").strip()
        if base:
            config["providers"].setdefault(provider_key, {})["base_url"] = base
            print(f"  {_check()} Endpoint: {base}")

    print()

    # ---- Phase 5: save ----
    config["provider"] = provider_key
    save_config(config)

    print(f"  {_check()} Setup complete! Active provider: {label}")
    print("  Config: ~/.therain2020-agent/config.yaml")
    print()
    print("  Try: therain2020 \"hello world\"")
    print()


def _show_provider_group(names: list[str]):
    for key, label, env_var, model, _, cost in PROVIDER_REGISTRY:
        if key not in names:
            continue
        env_status = "(env)" if env_var and _env_has(env_var) else ""
        desc = f"[{key}] {label} — {model} (~${cost}/1k)"
        if env_status:
            desc += f" {env_status}"
        print(f"      {desc}")


def _find_provider(key: str) -> tuple[str, str, str, str | None, float]:
    for pkey, label, env_var, model, base_url, cost in PROVIDER_REGISTRY:
        if pkey == key:
            return label, env_var, model, base_url, cost
    return key, "", "gpt-3.5-turbo", None, 0.0


def _save_key(config: dict, provider_key: str, api_key: str, env_var: str):
    prov = config.setdefault("providers", {}).setdefault(provider_key, {})
    prov["api_key"] = api_key
    if env_var:
        prov["env_var"] = env_var
    if env_var and _env_has(env_var):
        print(f"  {_check()} Using {env_var} ({_mask(api_key)})")
    else:
        print(f"  {_check()} Saved to {env_var}" if env_var else
              f"  {_check()} API key saved")


def _prompt_secret(prompt: str) -> str:
    val = input(prompt).strip()
    return val if val else ""


def _env_has(name: str) -> str | None:
    import os
    v = os.environ.get(name, "")
    return v if v else None


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "…" + s[-4:]


def _check() -> str:
    return "✓"
