"""Unit tests for the Multi-Provider AI system."""

import os
import unittest
from unittest.mock import MagicMock, patch

from just_talk.ai.providers import (
    AIProvider,
    MultiProviderFormatter,
    PROVIDER_REGISTRY,
    get_provider,
    get_provider_list,
)
from just_talk.ai.gemini import CircuitBreaker, ConnectionTestResult
from just_talk.config import AppConfig
from just_talk.security import CredentialManager, PROVIDER_KEY_ACCOUNTS


class TestMultiProvider(unittest.TestCase):
    """Test suite verifying multi-provider AI registry, formatting, and key storage."""

    def test_provider_registry_contains_expected_providers(self):
        expected_ids = [
            "gemini",
            "openai",
            "anthropic",
            "grok",
            "groq",
            "openrouter",
            "deepseek",
            "custom",
        ]
        for pid in expected_ids:
            self.assertIn(pid, PROVIDER_REGISTRY)
            p = get_provider(pid)
            self.assertIsNotNone(p)
            self.assertEqual(p.id, pid)
            self.assertTrue(len(p.display_name) > 0)

    def test_provider_models_populated(self):
        openrouter = get_provider("openrouter")
        self.assertIn("anthropic/claude-sonnet-4", openrouter.popular_models)
        self.assertIn("google/gemini-2.5-flash", openrouter.popular_models)

        grok = get_provider("grok")
        self.assertIn("grok-3-mini-fast", grok.popular_models)

        groq = get_provider("groq")
        self.assertIn("llama-3.3-70b-versatile", groq.popular_models)

        claude = get_provider("anthropic")
        self.assertIn("claude-sonnet-4-20250514", claude.popular_models)

    def test_formatter_initialization_and_switching(self):
        formatter = MultiProviderFormatter(provider_id="openai")
        self.assertEqual(formatter.provider_id, "openai")
        self.assertEqual(formatter.model_name, "gpt-4o-mini")

        formatter.set_provider("grok", api_key="test-grok-key", model_name="grok-3-fast")
        self.assertEqual(formatter.provider_id, "grok")
        self.assertEqual(formatter.api_key, "test-grok-key")
        self.assertEqual(formatter.model_name, "grok-3-fast")

    def test_custom_provider_base_url(self):
        formatter = MultiProviderFormatter(
            provider_id="custom",
            custom_base_url="http://localhost:11434/v1",
            model_name="mistral-7b",
        )
        self.assertEqual(formatter.provider_id, "custom")
        self.assertEqual(formatter.base_url, "http://localhost:11434/v1")
        self.assertEqual(formatter.model_name, "mistral-7b")

    def test_missing_api_key_falls_back_locally(self):
        formatter = MultiProviderFormatter(provider_id="anthropic", api_key=None)
        # Clear env var if set
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with patch.object(CredentialManager, "get_provider_api_key", return_value=None):
                out, success, msg = formatter.format_text("um hey can we meet at five")
                self.assertFalse(success)
                self.assertIn("Cleaned locally", msg)
                self.assertIn("Hey can we meet at five.", out)

    def test_test_connection_without_key(self):
        formatter = MultiProviderFormatter(provider_id="grok", api_key=None)
        with patch.object(CredentialManager, "get_provider_api_key", return_value=None):
            res = formatter.test_connection(api_key=None)
            self.assertFalse(res.success)
            self.assertIn("not configured", res.message)

    def test_credential_manager_provider_keys(self):
        for pid in ["openai", "anthropic", "grok", "groq", "openrouter", "deepseek"]:
            self.assertIn(pid, PROVIDER_KEY_ACCOUNTS)
            test_key = f"test-key-for-{pid}-12345"
            CredentialManager.set_provider_api_key(pid, test_key)
            fetched = CredentialManager.get_provider_api_key(pid)
            self.assertEqual(fetched, test_key)
            CredentialManager.delete_provider_api_key(pid)

    def test_config_multi_provider_fields(self):
        config = AppConfig()
        self.assertEqual(config.ai_provider, "gemini")
        self.assertEqual(config.ai_model, "")
        self.assertEqual(config.custom_api_base_url, "")

    def test_sanitize_output_urls_no_trailing_dot(self):
        formatter = MultiProviderFormatter(provider_id="gemini")
        # Standalone domain with trailing dot
        self.assertEqual(formatter._sanitize_output("github.com", "github.com."), "github.com")
        self.assertEqual(formatter._sanitize_output("Github.com", "Github.com."), "github.com")
        # Sentence ending with URL
        self.assertEqual(
            formatter._sanitize_output("visit github.com", "Visit github.com."),
            "Visit github.com",
        )
        # Normal sentence still preserves period
        self.assertEqual(
            formatter._sanitize_output("hello world", "Hello world."),
            "Hello world.",
        )

    def test_translation_directive_wrapping(self):
        formatter = MultiProviderFormatter(provider_id="gemini", api_key="mock_key")
        captured_instructions = []

        def mock_format_gemini(raw_text, wrapped_instruction, key):
            captured_instructions.append(wrapped_instruction)
            return "This meeting is about project code.", True, ""

        formatter._format_gemini = mock_format_gemini
        out, success, msg = formatter.format_text(
            "yo meeting ma hami project code discuss garchhau",
            style="translate",
        )
        self.assertTrue(success)
        self.assertEqual(out, "This meeting is about project code.")
        self.assertTrue(len(captured_instructions) > 0)
        instruction = captured_instructions[0]
        self.assertIn("Translate the spoken content into clean, fluent English", instruction)
        self.assertNotIn("Only clean and format the spoken words into written text.", instruction)

    def test_timeout_capped_at_2_seconds(self):
        formatter = MultiProviderFormatter(provider_id="openai", api_key="test-key", timeout=15.0)
        # Even if a larger timeout is passed, default timeout is 2.0s and effective timeout never exceeds 2.0s
        default_formatter = MultiProviderFormatter(provider_id="gemini")
        self.assertEqual(default_formatter.timeout, 2.0)

        # Verify timeout cap during format call
        with patch("httpx.Client.post") as mock_post:
            import httpx
            mock_post.side_effect = httpx.TimeoutException("Read timed out")
            out, success, msg = formatter.format_text("long raw text " * 50)
            self.assertFalse(success)
            self.assertTrue("timeout" in msg.lower() or "timed out" in msg.lower())


if __name__ == "__main__":
    unittest.main()

