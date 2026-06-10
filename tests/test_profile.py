import tempfile
import unittest
from pathlib import Path

from app.db import connect, init_db
from app.profile import process_feedback, seed_user_manual
from app.profile_ingest import HermesProfileIngestError, HermesProfileIngestResult
from app.repository import ProfileItemReviewDraft, RecommendationDraft, Repository


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "test.db")
        init_db(self.conn)
        self.repo = Repository(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_seed_user_manual_creates_profile_items(self):
        seed_user_manual(self.repo, "- 偏好实战书\n- 反感空洞趋势报告")
        rows = self.repo.top_profile_items()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["category"], "life_context")

    def test_feedback_updates_profile(self):
        rec_id = self._add_recommendation(theme="AI Agent 商业化")
        self.repo.add_feedback(rec_id, "like")
        processed = process_feedback(self.repo)
        rows = self.repo.top_profile_items()
        self.assertEqual(processed, 1)
        self.assertEqual(rows[0]["category"], "long_term_interest")
        self.assertEqual(rows[0]["content"], "AI Agent 商业化")

    def test_reason_code_is_persisted(self):
        rec_id = self._add_recommendation(theme="软件工程实践")
        feedback_id = self.repo.add_feedback(rec_id, "go_deeper", reason_code="knowledge_gap")

        row = self.conn.execute(
            "SELECT feedback_type, reason_code FROM feedback_events WHERE id = ?",
            (feedback_id,),
        ).fetchone()
        self.assertEqual(row["feedback_type"], "go_deeper")
        self.assertEqual(row["reason_code"], "knowledge_gap")

    def test_not_interested_already_know_updates_knowledge_background_only(self):
        rec_id = self._add_recommendation(theme="AI Agent 商业化")
        self.repo.add_feedback(rec_id, "not_interested", reason_code="already_know")

        process_feedback(self.repo)

        background = self._profile("knowledge_background", "已掌握：AI Agent 商业化")
        disliked = self.conn.execute("SELECT * FROM profile_items WHERE category = ?", ("disliked_topic",)).fetchall()
        self.assertIsNotNone(background)
        self.assertEqual(len(disliked), 0)

    def test_not_interested_wrong_timing_lowers_short_term_interest(self):
        self.repo.upsert_profile_item("short_term_interest", "AI Agent 商业化", 0.2, 0.1, {"source": "test"})
        rec_id = self._add_recommendation(theme="AI Agent 商业化")
        self.repo.add_feedback(rec_id, "not_interested", reason_code="wrong_timing")

        process_feedback(self.repo)

        row = self._profile("short_term_interest", "AI Agent 商业化")
        self.assertEqual(row["weight"], 0.62)

    def test_reason_codes_update_specific_profile_dimensions(self):
        cases = [
            ("not_interested", "too_theoretical", "reading_preference", "偏好更实战：软件工程实践"),
            ("not_interested", "too_hard", "knowledge_gap", "需要降低难度：软件工程实践"),
            ("like", "useful_methodology", "reading_preference", "偏好可复用方法论：软件工程实践"),
            ("already_read", "already_finished", "knowledge_background", "已读或熟悉：Test Book A"),
        ]
        for feedback_type, reason_code, category, content in cases:
            with self.subTest(reason_code=reason_code):
                rec_id = self._add_recommendation(theme="软件工程实践")
                self.repo.add_feedback(rec_id, feedback_type, reason_code=reason_code)
                process_feedback(self.repo)
                self.assertIsNotNone(self._profile(category, content))

    def test_like_solves_current_problem_updates_action_stage_and_gap(self):
        rec_id = self._add_recommendation(theme="软件工程实践")
        self.repo.add_feedback(rec_id, "like", reason_code="solves_current_problem")

        process_feedback(self.repo)

        self.assertIsNotNone(self._profile("action_stage", "当前正在解决：软件工程实践"))
        self.assertIsNotNone(self._profile("knowledge_gap", "当前问题相关缺口：软件工程实践"))

    def test_go_deeper_knowledge_gap_updates_gap_and_short_term_interest(self):
        rec_id = self._add_recommendation(theme="软件工程实践")
        self.repo.add_feedback(rec_id, "go_deeper", reason_code="knowledge_gap")

        process_feedback(self.repo)

        self.assertIsNotNone(self._profile("knowledge_gap", "软件工程实践"))
        self.assertIsNotNone(self._profile("short_term_interest", "软件工程实践"))

    def test_feedback_ingestor_applied_records_audit_and_profile_effect(self):
        rec_id = self._add_recommendation(theme="软件工程实践")
        feedback_id = self.repo.add_feedback(rec_id, "like", reason_code="useful_methodology", free_text="想多看工程实战")
        ingestor = _StaticIngestor(
            HermesProfileIngestResult(
                status="applied",
                should_update_native_memory=True,
                native_memory_path="/home/ubuntu/.hermes/memories/USER.md",
                memory_entry="[arc-reading-profile] User reading profile: 偏好工程实战。",
                rationale="explicit feedback",
                confidence=0.82,
                evidence_summary="like/useful_methodology",
                raw_response={"should_update_native_memory": True},
            )
        )

        processed = process_feedback(self.repo, profile_ingestor=ingestor)

        self.assertEqual(processed, 1)
        self.assertIsNotNone(self._profile("reading_preference", "偏好可复用方法论：软件工程实践"))
        audit = self._latest_hermes_profile_update(feedback_id)
        self.assertEqual(audit["status"], "applied")
        self.assertEqual(audit["should_update_native_memory"], 1)
        self.assertEqual(audit["memory_entry"], "[arc-reading-profile] User reading profile: 偏好工程实战。")
        feedback = self.conn.execute("SELECT processed_at FROM feedback_events WHERE id = ?", (feedback_id,)).fetchone()
        self.assertIsNotNone(feedback["processed_at"])

    def test_feedback_ingestor_skipped_records_audit_and_keeps_profile_effect(self):
        rec_id = self._add_recommendation(theme="软件工程实践")
        feedback_id = self.repo.add_feedback(rec_id, "neutral")
        ingestor = _StaticIngestor(
            HermesProfileIngestResult(
                status="skipped",
                should_update_native_memory=False,
                native_memory_path="/home/ubuntu/.hermes/memories/USER.md",
                memory_entry="",
                rationale="single weak signal",
                confidence=0.2,
                evidence_summary="neutral feedback",
                raw_response={"should_update_native_memory": False},
            )
        )

        processed = process_feedback(self.repo, profile_ingestor=ingestor)

        self.assertEqual(processed, 1)
        self.assertIsNotNone(self._profile("short_term_interest", "软件工程实践"))
        audit = self._latest_hermes_profile_update(feedback_id)
        self.assertEqual(audit["status"], "skipped")
        self.assertEqual(audit["should_update_native_memory"], 0)
        self.assertEqual(audit["memory_entry"], "")

    def test_feedback_ingestor_failure_records_audit_and_leaves_feedback_unprocessed(self):
        rec_id = self._add_recommendation(theme="软件工程实践")
        feedback_id = self.repo.add_feedback(rec_id, "like")

        with self.assertRaises(HermesProfileIngestError):
            process_feedback(self.repo, profile_ingestor=_FailingIngestor())

        audit = self._latest_hermes_profile_update(feedback_id)
        self.assertEqual(audit["status"], "failed")
        self.assertIn("boom", audit["error_message"])
        feedback = self.conn.execute("SELECT processed_at FROM feedback_events WHERE id = ?", (feedback_id,)).fetchone()
        self.assertIsNone(feedback["processed_at"])
        self.assertEqual(len(self.repo.top_profile_items()), 0)

    def test_recommendation_persists_hypothesis_fields(self):
        run_id = self.repo.create_run("test")
        rec_id = self.repo.add_recommendation(
            run_id,
            RecommendationDraft(
                title="Hypothesis Book",
                author="A",
                source_url="",
                slot_type="profile_fit",
                theme="软件工程实践",
                recommendation_reason="r",
                profile_mapping="m",
                system_hypothesis="测试用户是否需要系统设计基础",
                profile_dimensions=["knowledge_gap", "system_reliability"],
                expected_benefit="b",
                risk="risk",
                reading_suggestion="s",
                metadata={},
            ),
            __import__("datetime").date.today(),
        )

        row = self.conn.execute(
            "SELECT system_hypothesis, profile_dimensions FROM recommendations WHERE id = ?",
            (rec_id,),
        ).fetchone()
        self.assertEqual(row["system_hypothesis"], "测试用户是否需要系统设计基础")
        self.assertEqual(row["profile_dimensions"], '["knowledge_gap", "system_reliability"]')

    def test_profile_item_review_records_audit_and_downranks(self):
        self.repo.upsert_profile_item("long_term_interest", "火星纪事", 0.3, 0.4, {"source": "feedback", "book": "火星纪事"})
        item = self._profile("long_term_interest", "火星纪事")

        updated, event = self.repo.review_profile_item(
            ProfileItemReviewDraft(
                profile_item_id=int(item["id"]),
                action="inaccurate",
                note="这只是一次试探，不应当当成长期偏好",
            )
        )

        self.assertEqual(event["action"], "inaccurate")
        self.assertEqual(event["previous_weight"], 0.8)
        self.assertEqual(event["new_weight"], 0.55)
        self.assertLess(updated["confidence"], item["confidence"])
        rows = self.repo.profile_items_with_review_summary()
        self.assertEqual(rows[0]["review_count"], 1)
        self.assertEqual(rows[0]["inaccurate_count"], 1)
        self.assertEqual(rows[0]["latest_review_note"], "这只是一次试探，不应当当成长期偏好")

    def test_profile_item_confirm_increases_confidence_without_losing_evidence(self):
        self.repo.upsert_profile_item("reading_preference", "偏好工程实战", 0.1, 0.1, {"source": "manual"})
        item = self._profile("reading_preference", "偏好工程实战")

        updated, event = self.repo.review_profile_item(ProfileItemReviewDraft(profile_item_id=int(item["id"]), action="confirm"))

        self.assertEqual(event["action"], "confirm")
        self.assertGreater(updated["confidence"], item["confidence"])
        evidence = __import__("json").loads(updated["evidence_json"])
        self.assertEqual(evidence[0]["source"], "manual")

    def _add_recommendation(self, theme: str) -> int:
        run_id = self.repo.create_run("test")
        return self.repo.add_recommendation(
            run_id,
            RecommendationDraft(
                title="Test Book",
                author="A",
                source_url="",
                slot_type="profile_fit",
                theme=theme,
                recommendation_reason="r",
                profile_mapping="m",
                system_hypothesis=f"测试用户是否关注 {theme}",
                profile_dimensions=["long_term_interest", "business_strategy"],
                expected_benefit="b",
                risk="risk",
                reading_suggestion="s",
                metadata={},
            ),
            __import__("datetime").date.today(),
        )

    def _profile(self, category: str, content: str):
        return self.conn.execute(
            "SELECT * FROM profile_items WHERE category = ? AND content = ?",
            (category, content),
        ).fetchone()

    def _latest_hermes_profile_update(self, feedback_id: int):
        return self.conn.execute(
            """
            SELECT *
            FROM hermes_profile_update_events
            WHERE feedback_event_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (feedback_id,),
        ).fetchone()


class _StaticIngestor:
    def __init__(self, result: HermesProfileIngestResult):
        self.result = result

    def ingest_feedback(self, event):
        return self.result


class _FailingIngestor:
    def ingest_feedback(self, event):
        raise RuntimeError("boom")


if __name__ == "__main__":
    unittest.main()
