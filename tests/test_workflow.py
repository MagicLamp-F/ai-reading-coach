import tempfile
import unittest
from pathlib import Path

from app.db import connect, init_db
from app.repository import Repository
from app.workflow import FALLBACK_BOOKS
from app.workflow import ReadingCoachWorkflow


class FailingLLM:
    api_key = "test-key"
    model = "test-model"

    def complete_json(self, system_prompt, user_prompt):
        raise RuntimeError("HTTP request failed: HTTP Error 503: Service Unavailable")


class FailingSearch:
    def search_books(self, query, max_results=5):
        raise RuntimeError("HTTP request failed: HTTP Error 503: Service Unavailable")


class DisabledLark:
    def enabled(self):
        return False

    def send_recommendation(self, index, total, draft, links):
        return None

    def send_text(self, text):
        return None


class DisabledTelegram:
    def enabled(self):
        return False

    def send_message(self, text, markup=None):
        return None


class EmptySearch:
    def search_books(self, query, max_results=5):
        return []


class NoApiLLM:
    api_key = ""
    model = "test-model"

    def complete_json(self, system_prompt, user_prompt):
        return None


class CapturingLark:
    def __init__(self, summary_message_id=None):
        self.summary_message_id = summary_message_id
        self.summary_drafts = []

    def enabled(self):
        return True

    def send_recommendation(self, index, total, draft, links):
        return f"rec-{index}"

    def send_profile_test_summary(self, drafts):
        self.summary_drafts = list(drafts)
        return self.summary_message_id

    def send_text(self, text):
        return "text-id"


class ExplodingSummaryLark(CapturingLark):
    def send_profile_test_summary(self, drafts):
        self.summary_drafts = list(drafts)
        raise RuntimeError("lark unavailable")


class WorkflowTests(unittest.TestCase):
    def test_fallback_books_include_hypothesis_fields(self):
        for book in FALLBACK_BOOKS:
            self.assertTrue(book["system_hypothesis"])
            self.assertIsInstance(book["profile_dimensions"], list)
            self.assertGreaterEqual(len(book["profile_dimensions"]), 1)

    def test_daily_run_uses_fallbacks_when_external_services_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            init_db(conn)
            repo = Repository(conn)
            workflow = ReadingCoachWorkflow(
                repo=repo,
                search=FailingSearch(),
                llm=FailingLLM(),
                lark=DisabledLark(),
                telegram=DisabledTelegram(),
                channel="lark",
                public_base_url="http://localhost:8000",
                feedback_secret="secret",
                max_search_calls=3,
                max_model_calls=2,
            )

            run_id = workflow.run_daily_recommendations()

            run = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()
            recommendation_count = conn.execute("SELECT COUNT(*) AS count FROM recommendations").fetchone()["count"]
            self.assertEqual(run["status"], "success")
            self.assertEqual(recommendation_count, 3)
            conn.close()

    def test_daily_run_sends_lark_profile_test_summary_after_three_recommendations(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            init_db(conn)
            repo = Repository(conn)
            lark = CapturingLark(summary_message_id="summary-id")
            workflow = ReadingCoachWorkflow(
                repo=repo,
                search=EmptySearch(),
                llm=NoApiLLM(),
                lark=lark,
                telegram=DisabledTelegram(),
                channel="lark",
                public_base_url="http://localhost:8000",
                feedback_secret="secret",
                max_search_calls=3,
                max_model_calls=2,
            )

            run_id = workflow.run_daily_recommendations()

            run = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()
            recommendation_count = conn.execute("SELECT COUNT(*) AS count FROM recommendations WHERE run_id = ?", (run_id,)).fetchone()["count"]
            self.assertEqual(run["status"], "success")
            self.assertIsNone(run["warning_message"])
            self.assertEqual(recommendation_count, 3)
            self.assertEqual(len(lark.summary_drafts), 3)
            self.assertEqual(
                [draft.system_hypothesis for draft in lark.summary_drafts],
                [book["system_hypothesis"] for book in FALLBACK_BOOKS],
            )
            conn.close()

    def test_daily_run_records_warning_when_lark_profile_test_summary_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            init_db(conn)
            repo = Repository(conn)
            lark = ExplodingSummaryLark()
            workflow = ReadingCoachWorkflow(
                repo=repo,
                search=EmptySearch(),
                llm=NoApiLLM(),
                lark=lark,
                telegram=DisabledTelegram(),
                channel="lark",
                public_base_url="http://localhost:8000",
                feedback_secret="secret",
                max_search_calls=3,
                max_model_calls=2,
            )

            run_id = workflow.run_daily_recommendations()

            run = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()
            recommendation_count = conn.execute("SELECT COUNT(*) AS count FROM recommendations WHERE run_id = ?", (run_id,)).fetchone()["count"]
            self.assertEqual(run["status"], "success")
            self.assertEqual(recommendation_count, 3)
            self.assertIn("profile test summary lark send failed", run["warning_message"])
            self.assertIn("lark unavailable", run["warning_message"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
