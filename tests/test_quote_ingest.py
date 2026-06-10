import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.db import connect, init_db
from app.feedback import sign_reading_pack
from app.memory import HERMES_NATIVE_USER_MEMORY_MARKER
from app.quote_ingest import HermesQuoteIngestError, HermesQuoteProfileIngestor, QuoteProfileIngestService
from app.repository import ReadingPackDraft, ReadingQuoteDraft, RecommendationDraft, Repository


class QuoteIngestTests(unittest.TestCase):
    def test_quote_ingest_sends_batch_route_and_writes_native_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            native_memory = root / "USER.md"
            native_memory.write_text("[arc-reading-profile] User reading profile: 偏好文学。", encoding="utf-8")
            repo = _repo_with_quote(root)
            calls = []

            def runner(argv, **kwargs):
                calls.append({"argv": argv, "payload": json.loads(kwargs["input"])})
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout=json.dumps(
                        {
                            "should_update_native_memory": True,
                            "memory_entry": "[arc-reading-profile] User reading profile: 偏好有画面感、带命运转折的文学句子。",
                            "rationale": "batch has explicit note and quote evidence",
                            "confidence": 0.82,
                            "evidence_summary": "1 quote from Test Book",
                            "preference_summary": {"language_style": ["有画面感"], "themes": ["命运转折"]},
                        },
                        ensure_ascii=False,
                    ),
                    stderr="",
                )

            result = QuoteProfileIngestService(
                repo,
                HermesQuoteProfileIngestor(
                    command="/bin/hermes-profile",
                    timeout_seconds=3,
                    native_user_memory_path=native_memory,
                    native_user_memory_char_limit=500,
                    runner=runner,
                ),
            ).ingest_pending(limit=5)

            self.assertEqual(result.status, "applied")
            self.assertEqual(result.quote_count, 1)
            self.assertEqual(calls[0]["argv"], ["/bin/hermes-profile"])
            payload = calls[0]["payload"]
            self.assertEqual(payload["route"], "reading.quote.ingest")
            self.assertEqual(payload["output_schema"], "quote_profile_update_v1")
            self.assertEqual(payload["context"]["quote_batch"][0]["quote"], "这是一句想反复回味的原著句子")
            self.assertTrue(payload["constraints"]["batch_level_summary_required"])
            self.assertIn(HERMES_NATIVE_USER_MEMORY_MARKER, native_memory.read_text(encoding="utf-8"))
            quote = repo.recent_reading_quotes(limit=1)[0]
            audit = repo.conn.execute("SELECT * FROM hermes_quote_profile_update_events ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(quote["profile_ingest_status"], "applied")
            self.assertEqual(audit["status"], "applied")
            self.assertIn("有画面感", audit["preference_summary_json"])

    def test_quote_ingest_skip_marks_quotes_without_memory_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            native_memory = root / "USER.md"
            repo = _repo_with_quote(root)

            def runner(argv, **kwargs):
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout=json.dumps(
                        {
                            "should_update_native_memory": False,
                            "memory_entry": "",
                            "rationale": "single isolated quote",
                            "confidence": 0.2,
                            "evidence_summary": "weak signal",
                            "preference_summary": {"open_questions": ["needs more quotes"]},
                        }
                    ),
                    stderr="",
                )

            result = QuoteProfileIngestService(
                repo,
                HermesQuoteProfileIngestor("/bin/hermes-profile", 3, native_memory, 500, runner=runner),
            ).ingest_pending()

            self.assertEqual(result.status, "skipped")
            self.assertFalse(native_memory.exists())
            quote = repo.recent_reading_quotes(limit=1)[0]
            self.assertEqual(quote["profile_ingest_status"], "skipped")

    def test_quote_ingest_failure_records_audit_and_marks_failed_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _repo_with_quote(Path(tmp))

            def runner(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, stdout="not json", stderr="")

            result = QuoteProfileIngestService(
                repo,
                HermesQuoteProfileIngestor("/bin/hermes-profile", 3, Path(tmp) / "USER.md", 500, runner=runner),
            ).ingest_pending()

            self.assertEqual(result.status, "failed")
            quote = repo.recent_reading_quotes(limit=1)[0]
            audit = repo.conn.execute("SELECT * FROM hermes_quote_profile_update_events ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(quote["profile_ingest_status"], "failed")
            self.assertEqual(audit["status"], "failed")
            self.assertIn("invalid JSON", audit["error_message"])

    def test_quote_ingestor_raises_on_empty_command(self):
        with self.assertRaises(HermesQuoteIngestError):
            HermesQuoteProfileIngestor("", 3, Path("/tmp/USER.md"), 500).ingest_quotes([])


def _repo_with_quote(root: Path) -> Repository:
    conn = connect(root / "test.db")
    init_db(conn)
    repo = Repository(conn)
    run_id = repo.create_run("test")
    recommendation_id = repo.add_recommendation(
        run_id,
        RecommendationDraft(
            title="Test Book",
            author="A",
            source_url="",
            slot_type="profile_fit",
            theme="经典文学",
            recommendation_reason="r",
            profile_mapping="m",
            system_hypothesis="h",
            profile_dimensions=["reading_preference"],
            expected_benefit="b",
            risk="risk",
            reading_suggestion="s",
            metadata={},
        ),
        date.today(),
    )
    recommendation = repo.get_recommendation_detail(recommendation_id)
    pack_id = repo.add_reading_pack(
        ReadingPackDraft(
            recommendation_id=recommendation_id,
            book_id=int(recommendation["book_id"]),
            artifact_id=None,
            status="generated",
            route="reading.deep_read_pack",
            schema_version="deep_read_pack_v2",
            title="Test Book 快读包",
            summary="summary",
            content={"pack_title": "Test Book 快读包"},
            generator_provider="test",
        )
    )
    repo.add_reading_quote(
        ReadingQuoteDraft(
            reading_pack_id=pack_id,
            recommendation_id=recommendation_id,
            book_id=int(recommendation["book_id"]),
            selected_text="这是一句想反复回味的原著句子",
            note="语言很有画面感",
            module="overview",
            section_title="一句话主张",
        )
    )
    sign_reading_pack(pack_id, "secret")
    return repo


if __name__ == "__main__":
    unittest.main()
