import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings


class ConfigTests(unittest.TestCase):
    def test_settings_reads_tavily_key_from_file_without_env_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "api_key"
            key_path.write_text("test-tavily-key\n", encoding="utf-8")
            env = {
                "TAVILY_API_KEY_FILE": str(key_path),
                "DATABASE_URL": f"sqlite:///{tmp}/test.db",
            }
            with patch.dict(os.environ, env, clear=True):
                settings = Settings.from_env()

        self.assertEqual(settings.tavily_api_key, "test-tavily-key")
        self.assertEqual(settings.tavily_api_key_file, key_path)

    def test_settings_prefers_tavily_key_env_over_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "api_key"
            key_path.write_text("file-key\n", encoding="utf-8")
            env = {
                "TAVILY_API_KEY": "env-key",
                "TAVILY_API_KEY_FILE": str(key_path),
                "DATABASE_URL": f"sqlite:///{tmp}/test.db",
            }
            with patch.dict(os.environ, env, clear=True):
                settings = Settings.from_env()

        self.assertEqual(settings.tavily_api_key, "env-key")

    def test_settings_reads_daily_recommendation_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "DATABASE_URL": f"sqlite:///{tmp}/test.db",
                "DAILY_RECOMMENDATION_COUNT": "1",
                "SOURCE_AWARE_CANDIDATE_COUNT": "5",
            }
            with patch.dict(os.environ, env, clear=True):
                settings = Settings.from_env()

        self.assertEqual(settings.daily_recommendation_count, 1)
        self.assertEqual(settings.source_aware_candidate_count, 5)

    def test_settings_default_model_routes_use_hermes(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"DATABASE_URL": f"sqlite:///{tmp}/test.db"}
            with patch.dict(os.environ, env, clear=True):
                settings = Settings.from_env()

        self.assertEqual(settings.daily_recommendation_provider, "hermes-agent")
        self.assertEqual(settings.reading_pack_provider, "hermes-agent")
        self.assertEqual(settings.hermes_reflection_provider, "hermes-agent")

    def test_settings_reads_hermes_native_profile_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "DATABASE_URL": f"sqlite:///{tmp}/test.db",
                "HERMES_NATIVE_PROFILE_PATH": f"{tmp}/HERMES_NATIVE_PROFILE.md",
                "HERMES_SOUL_PATH": f"{tmp}/SOUL.md",
                "HERMES_NATIVE_PROFILE_MAX_CHARS": "1234",
            }
            with patch.dict(os.environ, env, clear=True):
                settings = Settings.from_env()

        self.assertEqual(settings.hermes_native_profile_path, Path(tmp) / "HERMES_NATIVE_PROFILE.md")
        self.assertEqual(settings.hermes_soul_path, Path(tmp) / "SOUL.md")
        self.assertEqual(settings.hermes_native_profile_max_chars, 1234)

    def test_settings_reads_lark_retry_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "DATABASE_URL": f"sqlite:///{tmp}/test.db",
                "LARK_MAX_SEND_ATTEMPTS": "4",
                "LARK_RETRY_BASE_SECONDS": "1.5",
                "LARK_RATE_LIMIT_COOLDOWN_SECONDS": "120",
            }
            with patch.dict(os.environ, env, clear=True):
                settings = Settings.from_env()

        self.assertEqual(settings.lark_max_send_attempts, 4)
        self.assertEqual(settings.lark_retry_base_seconds, 1.5)
        self.assertEqual(settings.lark_rate_limit_cooldown_seconds, 120)


if __name__ == "__main__":
    unittest.main()
