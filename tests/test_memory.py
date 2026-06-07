import tempfile
import unittest
import json
import subprocess
from pathlib import Path

from app.memory import (
    HERMES_MEMORY_ENTRY_DELIMITER,
    HERMES_NATIVE_USER_MEMORY_MARKER,
    HermesNativeProfileProvider,
    TRUNCATION_MARKER,
    build_daily_profile_context,
    build_native_profile_seed_context,
    hermes_profile_sync_status,
    load_long_term_memory_context,
    upsert_hermes_user_memory_entry,
)


class MemoryLoaderTests(unittest.TestCase):
    def test_missing_memory_files_degrade_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = load_long_term_memory_context(Path(tmp) / "missing")

        self.assertIn("暂无 Hermes long-term memory", context)

    def test_overlong_memory_is_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "USER.md").write_text("A" * 200, encoding="utf-8")
            (memory_dir / "MEMORY.md").write_text("B" * 200, encoding="utf-8")

            context = load_long_term_memory_context(memory_dir, max_chars=80)

        self.assertLessEqual(len(context), 80)
        self.assertIn(TRUNCATION_MARKER, context)

    def test_native_profile_provider_reads_arc_snapshot_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "HERMES_NATIVE_PROFILE.md"
            soul = root / "SOUL.md"
            snapshot.write_text("Reading Preferences: literary classics", encoding="utf-8")
            soul.write_text("SOUL fallback should not appear", encoding="utf-8")
            provider = HermesNativeProfileProvider(snapshot_path=snapshot, fallback_soul_path=soul)

            context = provider.load_context()

        self.assertIn("HERMES_NATIVE_PROFILE.md", context)
        self.assertIn("literary classics", context)
        self.assertNotIn("SOUL fallback", context)

    def test_native_profile_provider_falls_back_to_soul(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            soul = root / "SOUL.md"
            soul.write_text("Stable Identity: builder", encoding="utf-8")
            provider = HermesNativeProfileProvider(snapshot_path=root / "missing.md", fallback_soul_path=soul)

            context = provider.load_context()

        self.assertIn("SOUL.md fallback", context)
        self.assertIn("Stable Identity", context)

    def test_native_profile_provider_generates_snapshot_when_command_is_configured(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            calls.append(json.loads(input))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "markdown": "# HERMES_NATIVE_PROFILE\n\n## Reading Preferences\n- generated",
                        "hermes_user_memory_entry": (
                            "[arc-reading-profile] User reading profile: generated classics preference."
                        ),
                    }
                ),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "memory" / "HERMES_NATIVE_PROFILE.md"
            native_user_memory = root / "hermes" / "memories" / "USER.md"
            soul = root / "SOUL.md"
            soul.write_text("Stable Identity: builder", encoding="utf-8")
            provider = HermesNativeProfileProvider(
                snapshot_path=snapshot,
                fallback_soul_path=soul,
                generator_command="/tmp/hermes-route",
                native_user_memory_path=native_user_memory,
                runner=runner,
            )

            context = provider.load_context()
            self.assertTrue(snapshot.exists())
            self.assertIn("# HERMES_NATIVE_PROFILE", snapshot.read_text(encoding="utf-8"))
            self.assertIn("generated classics preference", native_user_memory.read_text(encoding="utf-8"))

        self.assertIn("generated", context)
        self.assertEqual(calls[0]["route"], "reading.profile.sync_snapshot")
        self.assertIn("arc_evidence", calls[0]["context"])

    def test_native_profile_provider_refreshes_insufficient_snapshot_with_arc_evidence(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            calls.append(json.loads(input))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "markdown": (
                            "# HERMES_NATIVE_PROFILE\n\n"
                            "## Reading Preferences\n- 偏好经典名著和高口碑科幻。\n\n"
                            "## Source Notes\n- Derived from ARC structured reading profile evidence."
                        ),
                        "hermes_user_memory_entry": "[arc-reading-profile] User reading profile: 偏好经典名著和高口碑科幻。",
                    }
                ),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "memory" / "HERMES_NATIVE_PROFILE.md"
            native_user_memory = root / "hermes" / "memories" / "USER.md"
            snapshot.parent.mkdir()
            snapshot.write_text(
                "# HERMES_NATIVE_PROFILE\n\n"
                "## Reading Preferences\nNot enough personal reading facts are present.",
                encoding="utf-8",
            )
            soul = root / "SOUL.md"
            soul.write_text("Hermes assistant identity.", encoding="utf-8")
            provider = HermesNativeProfileProvider(
                snapshot_path=snapshot,
                fallback_soul_path=soul,
                generator_command="/tmp/hermes-route",
                native_user_memory_path=native_user_memory,
                runner=runner,
            )

            context = provider.load_context(
                seed_context=build_native_profile_seed_context(
                    "偏好经典名著、高口碑文学与科幻作品",
                    "用户希望推荐尽量是书籍本身而不是技术文章",
                )
            )
            native_user_content = native_user_memory.read_text(encoding="utf-8")

        self.assertIn("偏好经典名著和高口碑科幻", context)
        self.assertIn("偏好经典名著和高口碑科幻", native_user_content)
        self.assertIn("ARC structured reading profile evidence", calls[0]["context"]["arc_evidence"])

    def test_native_profile_provider_syncs_existing_snapshot_to_hermes_user_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "HERMES_NATIVE_PROFILE.md"
            native_user_memory = root / "hermes" / "memories" / "USER.md"
            snapshot.write_text(
                "# HERMES_NATIVE_PROFILE\n\n## Reading Preferences\n- 偏好经典文学和高口碑科幻。",
                encoding="utf-8",
            )
            provider = HermesNativeProfileProvider(
                snapshot_path=snapshot,
                fallback_soul_path=root / "missing.md",
                native_user_memory_path=native_user_memory,
            )

            provider.load_context()
            content = native_user_memory.read_text(encoding="utf-8")

        self.assertIn(HERMES_NATIVE_USER_MEMORY_MARKER, content)
        self.assertIn("经典文学", content)
        self.assertNotIn("Open Questions", content)

    def test_hermes_user_memory_upsert_preserves_other_entries_and_replaces_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "USER.md"
            path.write_text(
                HERMES_MEMORY_ENTRY_DELIMITER.join(
                    [
                        "User prefers concise technical answers.",
                        "[arc-reading-profile] User reading profile: old.",
                    ]
                ),
                encoding="utf-8",
            )

            upsert_hermes_user_memory_entry(path, "[arc-reading-profile] User reading profile: new.")

            entries = path.read_text(encoding="utf-8").split(HERMES_MEMORY_ENTRY_DELIMITER)

        self.assertEqual(len(entries), 2)
        self.assertIn("concise technical", entries[0])
        self.assertIn("new", entries[1])
        self.assertNotIn("old", entries[1])

    def test_hermes_user_memory_normalizes_existing_profile_without_duplicate_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "USER.md"
            upsert_hermes_user_memory_entry(
                path,
                "# HERMES_NATIVE_PROFILE\n\n"
                "## Reading Preferences\n"
                "- 明确偏好推荐书籍本身。\n"
                "- 技术类阅读需要可开始路径。\n\n"
                "## Open Questions\n"
                "- 待验证问题不应进入 Hermes USER memory compact entry。\n",
            )

            content = path.read_text(encoding="utf-8")

        self.assertIn("[arc-reading-profile] User reading profile: Reading Preferences", content)
        self.assertNotIn("User reading profile: User reading profile", content)
        self.assertNotIn("Open Questions", content)

    def test_hermes_user_memory_upsert_fails_when_native_limit_would_be_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "USER.md"
            path.write_text("Existing entry that consumes budget.", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                upsert_hermes_user_memory_entry(
                    path,
                    "[arc-reading-profile] User reading profile: too long.",
                    char_limit=40,
                )

    def test_hermes_profile_sync_status_reports_snapshot_and_native_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "HERMES_NATIVE_PROFILE.md"
            native_user_memory = root / "hermes" / "memories" / "USER.md"
            snapshot.write_text("# HERMES_NATIVE_PROFILE\n\n## Reading Preferences\n- 经典文学", encoding="utf-8")
            upsert_hermes_user_memory_entry(native_user_memory, "[arc-reading-profile] User reading profile: 经典文学")

            status = hermes_profile_sync_status(snapshot, native_user_memory, preview_chars=80)

        self.assertTrue(status["snapshot_exists"])
        self.assertGreater(status["snapshot_chars"], 0)
        self.assertTrue(status["native_user_memory_exists"])
        self.assertTrue(status["arc_entry_present"])
        self.assertIn("经典文学", str(status["arc_entry_preview"]))

    def test_hermes_profile_sync_status_reports_disabled_native_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "missing.md"

            status = hermes_profile_sync_status(snapshot, None)

        self.assertFalse(status["snapshot_exists"])
        self.assertFalse(status["native_user_memory_enabled"])
        self.assertFalse(status["arc_entry_present"])

    def test_native_profile_provider_raises_when_generation_fails(self):
        def runner(argv, input, text, capture_output, timeout, check):
            return subprocess.CompletedProcess(argv, 3, stdout="", stderr="empty stdout")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            soul = root / "SOUL.md"
            soul.write_text("Stable Identity: builder", encoding="utf-8")
            provider = HermesNativeProfileProvider(
                snapshot_path=root / "memory" / "HERMES_NATIVE_PROFILE.md",
                fallback_soul_path=soul,
                generator_command="/tmp/hermes-route",
                runner=runner,
            )

            with self.assertRaises(RuntimeError):
                provider.load_context()

    def test_daily_profile_context_uses_priority_layers(self):
        context = build_daily_profile_context(
            hermes_native_profile_context="native profile",
            structured_profile_context="arc reading profile",
            long_term_memory_context="arc applied memory",
        )

        self.assertLess(context.index("Priority 1"), context.index("Priority 2"))
        self.assertLess(context.index("Priority 2"), context.index("Priority 3"))
        self.assertLess(context.index("native profile"), context.index("arc reading profile"))
        self.assertIn("Single-run weak signals", context)


if __name__ == "__main__":
    unittest.main()
