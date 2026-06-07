import tempfile
import unittest
from pathlib import Path

from app.db import connect, init_db
from app.memory import HermesNativeProfileProvider
from app.repository import BookSourceDraft, RecommendationDraft, Repository
from app.workflow import FALLBACK_BOOKS
from app.workflow import ReadingCoachWorkflow
from app.workflow import build_recommendation_history_context


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

    def send_recommendation(self, index, total, draft, links, reading_pack_preview=None):
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


class CandidateLLM:
    api_key = "test-key"
    model = "test-model"

    def complete_json(self, system_prompt, user_prompt):
        if '"themes"' in user_prompt:
            return {"themes": ["商业化", "软件设计", "知识管理"]}
        return {
            "books": [
                {
                    "title": f"Candidate {index}",
                    "author": "Author",
                    "source_url": "",
                    "slot_type": "profile_fit",
                    "theme": "商业化",
                    "recommendation_reason": "reason",
                    "profile_mapping": "mapping",
                    "system_hypothesis": "hypothesis",
                    "profile_dimensions": ["business_strategy"],
                    "expected_benefit": "benefit",
                    "risk": "risk",
                    "reading_suggestion": "suggestion",
                    "user_fit_score": 0.8,
                    "candidate_reason": f"candidate reason {index}",
                }
                for index in range(1, 5)
            ]
        }


class SourceAwareCollector:
    def __init__(self, repo, rich_titles):
        self.repo = repo
        self.rich_titles = set(rich_titles)

    def collect_for_book(self, book_id, title, author="", source_url=""):
        if title not in self.rich_titles:
            return []
        for index in range(3):
            self.repo.upsert_book_source(
                BookSourceDraft(
                    book_id=book_id,
                    source_type="review" if index < 2 else "public_page",
                    url=f"https://example.test/{title}/{index}",
                    title=f"{title} source {index}",
                    text_excerpt="source text " * 700,
                    metadata={"source": "test"},
                )
            )
        return []


class ExplodingReadingPackAgent:
    name = "exploding-reading-pack-agent"

    def generate_pack(self, prompt_context):
        raise RuntimeError("reading pack unavailable")


class CapturingLark:
    def __init__(self, summary_message_id=None):
        self.summary_message_id = summary_message_id
        self.summary_drafts = []
        self.reading_pack_previews = []
        self.sent_reading_pack_previews = []

    def enabled(self):
        return True

    def send_recommendation(self, index, total, draft, links, reading_pack_preview=None):
        self.reading_pack_previews.append(reading_pack_preview)
        return f"rec-{index}"

    def send_profile_test_summary(self, drafts):
        self.summary_drafts = list(drafts)
        return self.summary_message_id

    def send_reading_pack_preview(self, reading_pack_preview):
        self.sent_reading_pack_previews.append(reading_pack_preview)
        return f"pack-{len(self.sent_reading_pack_previews)}"

    def send_text(self, text):
        return "text-id"


class FailingRecommendationLark(CapturingLark):
    last_send_error = ""

    def send_recommendation(self, index, total, draft, links, reading_pack_preview=None):
        self.reading_pack_previews.append(reading_pack_preview)
        self.last_send_error = "status=200 code=11232 msg=frequency limited"
        return None


class RecoveringRecommendationLark(FailingRecommendationLark):
    def __init__(self):
        super().__init__()
        self.fail = True

    def send_recommendation(self, index, total, draft, links, reading_pack_preview=None):
        self.reading_pack_previews.append(reading_pack_preview)
        if self.fail:
            self.last_send_error = "status=200 code=11232 msg=frequency limited"
            return None
        self.last_send_error = ""
        return f"resent-{index}"


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

    def test_daily_run_can_send_one_recommendation_by_configuration(self):
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
                daily_recommendation_count=1,
            )

            run_id = workflow.run_daily_recommendations()

            run = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()
            recommendation_count = conn.execute("SELECT COUNT(*) AS count FROM recommendations WHERE run_id = ?", (run_id,)).fetchone()["count"]
            self.assertEqual(run["status"], "success")
            self.assertEqual(recommendation_count, 1)
            self.assertEqual(len(lark.reading_pack_previews), 1)
            self.assertIsNone(lark.reading_pack_previews[0])
            self.assertEqual(lark.summary_drafts, [])
            conn.close()

    def test_daily_run_queues_lark_recommendation_delivery_failure_without_failing_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            init_db(conn)
            repo = Repository(conn)
            lark = FailingRecommendationLark()
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
                daily_recommendation_count=1,
            )

            run_id = workflow.run_daily_recommendations()

            run = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()
            recommendation = conn.execute("SELECT * FROM recommendations WHERE run_id = ?", (run_id,)).fetchone()
            outbox = conn.execute("SELECT * FROM delivery_outbox WHERE recommendation_id = ?", (recommendation["id"],)).fetchone()
            self.assertEqual(run["status"], "success")
            self.assertIn("recommendation delivery queued", run["warning_message"])
            self.assertIsNone(recommendation["message_id"])
            self.assertEqual(outbox["status"], "pending")
            self.assertEqual(outbox["message_type"], "recommendation")
            self.assertIn("11232", outbox["last_error"])
            conn.close()

    def test_resend_pending_deliveries_sends_queued_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            init_db(conn)
            repo = Repository(conn)
            lark = RecoveringRecommendationLark()
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
                daily_recommendation_count=1,
            )
            run_id = workflow.run_daily_recommendations()
            conn.execute("UPDATE delivery_outbox SET next_attempt_at = CURRENT_TIMESTAMP")
            lark.fail = False

            sent = workflow.resend_pending_deliveries()

            recommendation = conn.execute("SELECT * FROM recommendations WHERE run_id = ?", (run_id,)).fetchone()
            outbox = conn.execute("SELECT * FROM delivery_outbox WHERE recommendation_id = ?", (recommendation["id"],)).fetchone()
            self.assertEqual(sent, 1)
            self.assertEqual(recommendation["message_id"], "resent-1")
            self.assertEqual(outbox["status"], "sent")
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

    def test_daily_run_auto_generates_reading_packs_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            conn = connect(tmp_path / "test.db")
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
                memory_dir=tmp_path / "memory",
                reading_packs_enabled=True,
                reading_pack_library_dir=tmp_path / "library",
            )

            run_id = workflow.run_daily_recommendations()

            run = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()
            pack_count = conn.execute("SELECT COUNT(*) AS count FROM reading_packs").fetchone()["count"]
            artifact_count = conn.execute("SELECT COUNT(*) AS count FROM artifacts WHERE artifact_type = 'reading_pack'").fetchone()["count"]
            self.assertEqual(run["status"], "success")
            self.assertEqual(pack_count, 3)
            self.assertEqual(artifact_count, 3)
            self.assertEqual(len(lark.reading_pack_previews), 3)
            self.assertTrue(all(preview is not None for preview in lark.reading_pack_previews))
            self.assertEqual(len(lark.sent_reading_pack_previews), 0)
            artifact_paths = [
                row["path"]
                for row in conn.execute("SELECT path FROM artifacts WHERE artifact_type = 'reading_pack'")
            ]
            self.assertTrue(all(Path(path).exists() for path in artifact_paths))
            conn.close()

    def test_daily_run_fails_when_hermes_reading_pack_agent_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            conn = connect(tmp_path / "test.db")
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
                daily_recommendation_count=1,
                memory_dir=tmp_path / "memory",
                reading_packs_enabled=True,
                reading_pack_library_dir=tmp_path / "library",
                reading_pack_agent=ExplodingReadingPackAgent(),
            )

            with self.assertRaises(RuntimeError):
                workflow.run_daily_recommendations()

            run = conn.execute("SELECT * FROM run_logs ORDER BY id DESC LIMIT 1").fetchone()
            recommendation = conn.execute("SELECT * FROM recommendations WHERE run_id = ?", (run["id"],)).fetchone()
            pack_count = conn.execute("SELECT COUNT(*) AS count FROM reading_packs").fetchone()["count"]
            self.assertEqual(run["status"], "failed")
            self.assertIn("reading pack unavailable", run["error_message"])
            self.assertIsNotNone(recommendation)
            self.assertIsNone(recommendation["message_id"])
            self.assertEqual(len(lark.reading_pack_previews), 0)
            self.assertEqual(len(lark.sent_reading_pack_previews), 0)
            self.assertEqual(pack_count, 0)
            conn.close()

    def test_daily_run_source_aware_selects_only_source_qualified_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            conn = connect(tmp_path / "test.db")
            init_db(conn)
            repo = Repository(conn)
            workflow = ReadingCoachWorkflow(
                repo=repo,
                search=EmptySearch(),
                llm=CandidateLLM(),
                lark=DisabledLark(),
                telegram=DisabledTelegram(),
                channel="lark",
                public_base_url="http://localhost:8000",
                feedback_secret="secret",
                max_search_calls=3,
                max_model_calls=2,
                source_collector=SourceAwareCollector(repo, {"Candidate 1", "Candidate 3"}),
                source_aware_recommendations=True,
                source_aware_candidate_count=4,
                source_min_coverage_score=0.5,
            )

            run_id = workflow.run_daily_recommendations()

            selected_titles = [
                row["title"]
                for row in conn.execute(
                    """
                    SELECT b.title
                    FROM recommendations r
                    JOIN books b ON b.id = r.book_id
                    WHERE r.run_id = ?
                    ORDER BY r.id
                    """,
                    (run_id,),
                )
            ]
            candidate_rows = repo.list_recommendation_candidates(run_id)
            selected_candidates = [row for row in candidate_rows if row["status"] == "selected"]
            rejected_candidates = [row for row in candidate_rows if row["status"] == "rejected"]
            run = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()

            self.assertEqual(set(selected_titles), {"Candidate 1", "Candidate 3"})
            self.assertEqual(len(selected_candidates), 2)
            self.assertEqual(len(rejected_candidates), 2)
            self.assertIn("selected fewer than 3", run["warning_message"])
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
            (memory_dir / "HERMES_NATIVE_PROFILE.md").write_text(
                "# HERMES_NATIVE_PROFILE\n\nReading Preferences: 经典文学和高口碑科幻",
                encoding="utf-8",
            )
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
                self.assertIn("Priority 1: Hermes native USER memory reading profile", user_prompt)
                self.assertIn("Priority 3: ARC inferred reading profile", user_prompt)
                self.assertIn("Priority 4: ARC applied reflection memory", user_prompt)
                self.assertLess(user_prompt.index("Reading Preferences"), user_prompt.index("偏好工程实践"))
                self.assertIn("偏好工程实践", user_prompt)
                self.assertIn("经典文学和高口碑科幻", user_prompt)
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
                hermes_native_profile_provider=HermesNativeProfileProvider(
                    snapshot_path=tmp_path / "missing-native.md",
                    fallback_soul_path=tmp_path / "missing-soul.md",
                ),
            )

            run_id = workflow.run_daily_recommendations()

            run = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()
            self.assertEqual(run["status"], "success")
            self.assertIn("暂无 Hermes native USER memory reading profile", llm.prompts[0][1])
            self.assertIn("暂无 Hermes long-term memory", llm.prompts[0][1])
            conn.close()

    def test_daily_run_includes_recommendation_history_context_in_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            conn = connect(tmp_path / "test.db")
            init_db(conn)
            repo = Repository(conn)
            run_id = repo.create_run("seed")
            rec_id = repo.add_recommendation(
                run_id,
                RecommendationDraft(
                    title="三体",
                    author="刘慈欣",
                    source_url="",
                    slot_type="profile_fit",
                    theme="科幻经典",
                    recommendation_reason="r",
                    profile_mapping="m",
                    system_hypothesis="h",
                    profile_dimensions=["science_fiction"],
                    expected_benefit="b",
                    risk="risk",
                    reading_suggestion="s",
                    metadata={},
                ),
                __import__("datetime").date.today(),
            )
            repo.add_feedback(rec_id, "already_read", reason_code="already_finished")
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
                memory_dir=tmp_path / "memory",
                hermes_native_profile_provider=HermesNativeProfileProvider(
                    snapshot_path=tmp_path / "missing-native.md",
                    fallback_soul_path=tmp_path / "missing-soul.md",
                ),
            )

            workflow.run_daily_recommendations()
            history_context = build_recommendation_history_context(repo)

            self.assertIn("Hard exclusions", history_context)
            self.assertIn("三体 / 刘慈欣: user marked already_read", history_context)
            for _, user_prompt in llm.prompts:
                self.assertIn("推荐历史上下文", user_prompt)
                self.assertIn("三体 / 刘慈欣: user marked already_read", user_prompt)
            conn.close()

    def test_recommendation_history_context_includes_distribution_fatigue_and_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            init_db(conn)
            repo = Repository(conn)
            seed_run_id = repo.create_run("seed")
            first_id = repo.add_recommendation(
                seed_run_id,
                RecommendationDraft(
                    title="一句顶一万句",
                    author="刘震云",
                    source_url="",
                    slot_type="profile_fit",
                    theme="当代文学",
                    recommendation_reason="r",
                    profile_mapping="m",
                    system_hypothesis="h",
                    profile_dimensions=["literature"],
                    expected_benefit="b",
                    risk="risk",
                    reading_suggestion="s",
                    metadata={},
                ),
                __import__("datetime").date.today(),
            )
            second_id = repo.add_recommendation(
                seed_run_id,
                RecommendationDraft(
                    title="一句顶一万句",
                    author="刘震云",
                    source_url="",
                    slot_type="profile_fit",
                    theme="当代文学",
                    recommendation_reason="r",
                    profile_mapping="m",
                    system_hypothesis="h",
                    profile_dimensions=["literature"],
                    expected_benefit="b",
                    risk="risk",
                    reading_suggestion="s",
                    metadata={},
                ),
                __import__("datetime").date.today(),
            )
            third_id = repo.add_recommendation(
                seed_run_id,
                RecommendationDraft(
                    title="营销增长实战",
                    author="Author",
                    source_url="",
                    slot_type="exploration",
                    theme="商业增长",
                    recommendation_reason="r",
                    profile_mapping="m",
                    system_hypothesis="h",
                    profile_dimensions=["business"],
                    expected_benefit="b",
                    risk="risk",
                    reading_suggestion="s",
                    metadata={},
                ),
                __import__("datetime").date.today(),
            )
            repo.add_feedback(first_id, "like", reason_code="topic_matches", free_text="文学气质对")
            repo.add_feedback(second_id, "go_deeper", reason_code="want_reading_path")
            repo.add_feedback(third_id, "not_interested", reason_code="too_marketing")

            history_context = build_recommendation_history_context(repo)

            self.assertIn("Window summary", history_context)
            self.assertIn("Recent exact-title cooldown", history_context)
            self.assertIn("一句顶一万句 / 刘震云: recommended recently", history_context)
            self.assertIn("Feedback distribution", history_context)
            self.assertIn("type=喜欢 (like): 1", history_context)
            self.assertIn("reason=营销味太重 (too_marketing): 1", history_context)
            self.assertIn("Repeated exact-title signals", history_context)
            self.assertIn("一句顶一万句 / 刘震云: recommended 2 times", history_context)
            self.assertIn("Positive theme signals", history_context)
            self.assertIn("当代文学: 2 positive feedback event(s)", history_context)
            self.assertIn("Negative theme signals", history_context)
            self.assertIn("商业增长: 1 negative feedback event(s)", history_context)
            conn.close()

    def test_daily_run_fails_when_all_candidates_are_hard_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            conn = connect(tmp_path / "test.db")
            init_db(conn)
            repo = Repository(conn)
            seed_run_id = repo.create_run("seed")
            rec_id = repo.add_recommendation(
                seed_run_id,
                RecommendationDraft(
                    title="Memory Book 1",
                    author="Hermes",
                    source_url="",
                    slot_type="profile_fit",
                    theme="长期记忆主题",
                    recommendation_reason="r",
                    profile_mapping="m",
                    system_hypothesis="h",
                    profile_dimensions=["long_term_memory"],
                    expected_benefit="b",
                    risk="risk",
                    reading_suggestion="s",
                    metadata={},
                ),
                __import__("datetime").date.today(),
            )
            repo.add_feedback(rec_id, "already_read", reason_code="already_finished")
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
                daily_recommendation_count=1,
                memory_dir=tmp_path / "memory",
                hermes_native_profile_provider=HermesNativeProfileProvider(
                    snapshot_path=tmp_path / "missing-native.md",
                    fallback_soul_path=tmp_path / "missing-soul.md",
                ),
            )

            with self.assertRaises(RuntimeError):
                workflow.run_daily_recommendations()

            run = conn.execute("SELECT * FROM run_logs ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(run["status"], "failed")
            self.assertIn("hard-excluded", run["error_message"])
            self.assertIn("hard-excluded recommendation candidates removed", run["warning_message"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
