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


class PromptCapturingLLM:
    api_key = "test-key"
    model = "test-model"

    def __init__(self):
        self.prompts = []

    def complete_json(self, system_prompt, user_prompt):
        self.prompts.append((system_prompt, user_prompt))
        if '"themes"' in user_prompt:
            return {"themes": ["长期记忆主题", "结构化画像主题", "探索主题"]}
        return {
            "books": [
                {
                    "title": f"Memory Book {index}",
                    "author": "Hermes",
                    "source_url": "",
                    "slot_type": "profile_fit" if index < 3 else "exploration",
                    "theme": "长期记忆主题",
                    "recommendation_reason": "r",
                    "profile_mapping": "m",
                    "system_hypothesis": "测试 Hermes 长期记忆是否改善推荐",
                    "profile_dimensions": ["long_term_memory"],
                    "expected_benefit": "b",
                    "risk": "risk",
                    "reading_suggestion": "s",
                }
                for index in range(1, 4)
            ]
        }


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

    def test_daily_run_treats_empty_lark_profile_summary_message_id_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            init_db(conn)
            repo = Repository(conn)
            lark = CapturingLark(summary_message_id="")
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
            self.assertEqual(run["status"], "success")
            self.assertIsNone(run["warning_message"])
            self.assertEqual(len(lark.summary_drafts), 3)
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

    def test_daily_run_includes_applied_memory_files_in_theme_and_recommendation_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            memory_dir = tmp_path / "memory"
            memory_dir.mkdir()
            (memory_dir / "USER.md").write_text("# USER\n\n稳定偏好：系统设计书籍", encoding="utf-8")
            (memory_dir / "MEMORY.md").write_text("# MEMORY\n\n下周策略：减少趋势报告", encoding="utf-8")
            (memory_dir / "reflections").mkdir()
            (memory_dir / "reflections" / "reflection_99.md").write_text(
                "draft-only signal must not appear",
                encoding="utf-8",
            )
            conn = connect(tmp_path / "test.db")
            init_db(conn)
            repo = Repository(conn)
            repo.upsert_profile_item("reading_preference", "偏好工程实践", 0.2, 0.2, {"source": "test"})
            llm = PromptCapturingLLM()
            workflow = ReadingCoachWorkflow(
                repo=repo,
                search=EmptySearch(),
                llm=llm,
                lark=DisabledLark(),
                telegram=DisabledTelegram(),
                channel="lark",
                public_base_url="http://localhost:8000",
                feedback_secret="secret",
                max_search_calls=3,
                max_model_calls=2,
                memory_dir=memory_dir,
            )

            workflow.run_daily_recommendations()

            self.assertEqual(len(llm.prompts), 2)
            for _, user_prompt in llm.prompts:
                self.assertIn("SQLite structured profile", user_prompt)
                self.assertIn("Hermes long-term memory", user_prompt)
                self.assertIn("偏好工程实践", user_prompt)
                self.assertIn("稳定偏好：系统设计书籍", user_prompt)
                self.assertIn("下周策略：减少趋势报告", user_prompt)
                self.assertNotIn("draft-only signal", user_prompt)
            conn.close()

    def test_daily_run_missing_memory_files_does_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            conn = connect(tmp_path / "test.db")
            init_db(conn)
            repo = Repository(conn)
            llm = PromptCapturingLLM()
            workflow = ReadingCoachWorkflow(
                repo=repo,
                search=EmptySearch(),
                llm=llm,
                lark=DisabledLark(),
                telegram=DisabledTelegram(),
                channel="lark",
                public_base_url="http://localhost:8000",
                feedback_secret="secret",
                max_search_calls=3,
                max_model_calls=2,
                memory_dir=tmp_path / "missing-memory",
            )

            run_id = workflow.run_daily_recommendations()

            run = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()
            self.assertEqual(run["status"], "success")
            self.assertIn("暂无 Hermes long-term memory", llm.prompts[0][1])
            conn.close()


if __name__ == "__main__":
    unittest.main()
