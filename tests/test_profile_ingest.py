import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.memory import HERMES_NATIVE_USER_MEMORY_MARKER
from app.profile_ingest import HermesFeedbackProfileIngestor, HermesProfileIngestError


class HermesFeedbackProfileIngestorTests(unittest.TestCase):
    def test_ingest_feedback_sends_profile_update_route_and_writes_native_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            native_memory = Path(tmp) / "USER.md"
            calls = []

            def runner(argv, **kwargs):
                calls.append({"argv": argv, "payload": json.loads(kwargs["input"])})
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout=json.dumps(
                        {
                            "should_update_native_memory": True,
                            "memory_entry": "[arc-reading-profile] User reading profile: 偏好工程实战。",
                            "rationale": "explicit correction",
                            "confidence": 0.9,
                            "evidence_summary": "like feedback with free text",
                        },
                        ensure_ascii=False,
                    ),
                    stderr="",
                )

            result = HermesFeedbackProfileIngestor(
                command="/bin/hermes-profile",
                timeout_seconds=3,
                native_user_memory_path=native_memory,
                native_user_memory_char_limit=500,
                runner=runner,
            ).ingest_feedback(_event())

            self.assertEqual(result.status, "applied")
            self.assertEqual(calls[0]["argv"], ["/bin/hermes-profile"])
            self.assertEqual(calls[0]["payload"]["route"], "reading.feedback.ingest")
            self.assertEqual(calls[0]["payload"]["output_schema"], "profile_update_v1")
            self.assertTrue(calls[0]["payload"]["constraints"]["do_not_modify_memories"])
            self.assertIn(HERMES_NATIVE_USER_MEMORY_MARKER, native_memory.read_text(encoding="utf-8"))

    def test_ingest_feedback_treats_string_false_as_skip_without_memory_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            native_memory = Path(tmp) / "USER.md"

            def runner(argv, **kwargs):
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout=json.dumps(
                        {
                            "should_update_native_memory": "false",
                            "memory_entry": "[arc-reading-profile] User reading profile: should not write.",
                            "rationale": "weak signal",
                            "confidence": "0.1",
                            "evidence_summary": "neutral",
                        }
                    ),
                    stderr="",
                )

            result = HermesFeedbackProfileIngestor(
                command="/bin/hermes-profile",
                timeout_seconds=3,
                native_user_memory_path=native_memory,
                native_user_memory_char_limit=500,
                runner=runner,
            ).ingest_feedback(_event())

            self.assertEqual(result.status, "skipped")
            self.assertFalse(result.should_update_native_memory)
            self.assertFalse(native_memory.exists())

    def test_ingest_feedback_raises_on_invalid_json(self):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout="not json", stderr="")

        ingestor = HermesFeedbackProfileIngestor(
            command="/bin/hermes-profile",
            timeout_seconds=3,
            native_user_memory_path=Path("/tmp/USER.md"),
            native_user_memory_char_limit=500,
            runner=runner,
        )

        with self.assertRaises(HermesProfileIngestError):
            ingestor.ingest_feedback(_event())


def _event():
    return {
        "id": 12,
        "recommendation_id": 34,
        "feedback_type": "like",
        "reason_code": "useful_methodology",
        "free_text": "想多看工程实战",
        "created_at": "2026-06-07 10:00:00",
        "title": "Test Book",
        "author": "A",
        "theme": "软件工程实践",
        "slot_type": "profile_fit",
        "profile_mapping": "m",
    }


if __name__ == "__main__":
    unittest.main()
