"""Credential guard. 类比: kernel keyring.

API keys and secrets stay in Agent Core. LLM never sees raw values.
"""

import os

import structlog

logger = structlog.get_logger()


class CredentialGuard:
    """Protects credentials from LLM exposure. 类比: kernel key retention service."""

    def __init__(self):
        self._keyring: dict[str, str] = {}       # name → value
        self._env_refs: dict[str, str] = {}      # name → env_var_name

    def register(self, name: str, value: str = "", env_var: str = ""):
        """Register a credential from value or env var."""
        if env_var:
            self._env_refs[name] = env_var
            val = os.getenv(env_var, "")
            if val:
                self._keyring[name] = val
        elif value:
            self._keyring[name] = value
        logger.info("credential_registered", name=name)

    def mask_for_llm(self, text: str) -> str:
        """Replace credential values in text with env var references.

        Used on prompt text before sending to LLM.
        """
        for name, value in self._keyring.items():
            if value and len(value) > 4 and value in text:
                text = text.replace(value, f"${{{name}}}")
        return text

    def inject_for_tool(self, params: dict) -> dict:
        """Inject real credential values into tool call parameters.

        Agent Core performs this injection. LLM never participates.
        """
        result = {}
        for key, val in params.items():
            if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
                ref_name = val[2:-1]
                if ref_name in self._keyring:
                    result[key] = self._keyring[ref_name]
                    continue
            result[key] = val
        return result

    def redact_output(self, text: str) -> str:
        """Check if LLM output leaked credential values. Raises on detection."""
        for name, value in self._keyring.items():
            if value and len(value) > 4 and value in text:
                logger.error("credential_leak_detected", credential=name)
                raise CredentialLeakWarning(
                    f"LLM output contained credential '{name}'. Output blocked."
                )
        return text

    def check_env_ref(self, text: str) -> list[str]:
        """Check if text references env var names that could be sensitive."""
        referenced = []
        for name, env_var in self._env_refs.items():
            if env_var.lower() in text.lower():
                referenced.append(name)
        return referenced


class CredentialLeakWarning(Exception):
    """Raised when LLM output contains a credential value."""
    pass
