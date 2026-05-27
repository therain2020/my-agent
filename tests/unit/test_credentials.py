"""Tests for CredentialGuard."""


import pytest

from agent.security.credentials import CredentialGuard, CredentialLeakWarning


class TestCredentialGuard:
    def test_mask_value_in_text(self):
        guard = CredentialGuard()
        guard.register("API_KEY", value="sk-secret-12345678")
        masked = guard.mask_for_llm("Use key: sk-secret-12345678 to call API")
        assert "sk-secret-12345678" not in masked
        assert "${API_KEY}" in masked

    def test_no_mask_on_short_values(self):
        guard = CredentialGuard()
        guard.register("SHORT", value="xy")
        text = "The value is xy"
        masked = guard.mask_for_llm(text)
        assert "xy" in masked  # Too short to mask safely

    def test_inject_for_tool(self):
        guard = CredentialGuard()
        guard.register("DB_PASS", value="s3cret")
        params = {"host": "localhost", "password": "${DB_PASS}"}
        injected = guard.inject_for_tool(params)
        assert injected["password"] == "s3cret"
        assert injected["host"] == "localhost"

    def test_redact_detects_leak(self):
        guard = CredentialGuard()
        guard.register("SECRET", value="super-secret-token-42")
        with pytest.raises(CredentialLeakWarning):
            guard.redact_output("Here is the key: super-secret-token-42")

    def test_redact_passes_clean_output(self):
        guard = CredentialGuard()
        guard.register("SECRET", value="super-secret-token-42")
        result = guard.redact_output("Here is a normal response")
        assert "normal" in result
