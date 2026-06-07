import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db import connect, init_db
from app.feedback import sign_feedback_free_text, sign_guided_reading_day, sign_reading_pack
from app.guided_reading import GuidedReadingService
from app.repository import ReadingPackDraft, RecommendationDraft, Repository


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.library_dir = Path(self.tmp.name) / "library"
        conn = connect(self.db_path)
        init_db(conn)
        self.repo = Repository(conn)
        self.recommendation_id = self._add_recommendation()
        conn.close()
        self.settings = SimpleNamespace(
            database_path=self.db_path,
            feedback_secret="secret",
            public_base_url="http://testserver",
            reading_pack_library_dir=self.library_dir,
        )
        self.client = TestClient(create_app(self.settings))

    def tearDown(self):
        self.tmp.cleanup()

    def test_healthz_and_metrics(self):
        response = self.client.get("/api/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

        metrics = self.client.get("/api/metrics")
        self.assertEqual(metrics.status_code, 200)
        self.assertIn("arc_api_requests_total", metrics.text)

    def test_reading_pack_json_and_feedback_submission(self):
        reading_pack_id = self._add_reading_pack()
        token = sign_reading_pack(reading_pack_id, self.settings.feedback_secret)

        response = self.client.get(f"/api/reading-packs/{reading_pack_id}", params={"token": token, "module": "argument"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["book"]["title"], "Test Book")
        self.assertEqual(payload["current_module"], "argument")
        self.assertGreaterEqual(len(payload["sections"]), 1)
        reason = payload["feedback_options"][0]["reasons"][0]

        saved = self.client.post(
            f"/api/reading-packs/{reading_pack_id}/feedback",
            json={
                "feedback_type": "like",
                "reason_code": reason["code"],
                "token": reason["token"],
                "free_text": "正好需要",
            },
        )

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["status"], "saved")
        row = self._latest_feedback()
        self.assertEqual(row["feedback_type"], "like")
        self.assertEqual(row["reason_code"], reason["code"])
        self.assertEqual(row["free_text"], "正好需要")

    def test_reading_pack_rejects_bad_signature(self):
        reading_pack_id = self._add_reading_pack()

        response = self.client.get(f"/api/reading-packs/{reading_pack_id}", params={"token": "bad"})

        self.assertEqual(response.status_code, 403)

    def test_guided_day_json_and_feedback_submission(self):
        day_id = self._add_guided_reading_plan()
        token = sign_guided_reading_day(day_id, self.settings.feedback_secret)

        response = self.client.get(f"/api/guided-reading/days/{day_id}", params={"token": token})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["book"]["title"], "低耐心阅读")
        self.assertEqual(payload["day_number"], 1)
        self.assertIn("token", payload["days"][0])

        saved = self.client.post(
            f"/api/guided-reading/days/{day_id}/feedback",
            json={"token": token, "event_type": "completed", "note": "读完了"},
        )

        self.assertEqual(saved.status_code, 200)
        conn = connect(self.db_path)
        try:
            day = conn.execute("SELECT status FROM reading_plan_days WHERE id = ?", (day_id,)).fetchone()
            event = conn.execute("SELECT * FROM reading_progress_events ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(day["status"], "completed")
            self.assertEqual(event["event_type"], "completed")
            self.assertIn("读完了", event["detail_json"])
        finally:
            conn.close()

    def test_admin_can_list_plans(self):
        self._add_guided_reading_plan()
        admin_token = sign_feedback_free_text(0, self.settings.feedback_secret)

        response = self.client.get("/api/admin/reading-plans", params={"admin_token": admin_token})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["plans"][0]["book_title"], "低耐心阅读")

    def _add_recommendation(self) -> int:
        run_id = self.repo.create_run("test")
        return self.repo.add_recommendation(
            run_id,
            RecommendationDraft(
                title="Test Book",
                author="A",
                source_url="",
                slot_type="profile_fit",
                theme="AI Agent 商业化",
                recommendation_reason="r",
                profile_mapping="m",
                system_hypothesis="测试用户是否关注 AI Agent 商业化",
                profile_dimensions=["long_term_interest", "business_strategy"],
                expected_benefit="b",
                risk="risk",
                reading_suggestion="s",
                metadata={},
            ),
            __import__("datetime").date.today(),
        )

    def _add_reading_pack(self) -> int:
        conn = connect(self.db_path)
        try:
            repo = Repository(conn)
            artifact_id = repo.add_or_update_artifact(
                artifact_type="reading_pack",
                title="Test Book Pack",
                path=str(Path(self.tmp.name) / "reading-pack.md"),
                sha256="test-sha",
                content_type="text/markdown",
                metadata={"module_paths": ["modules/01-overview.md"]},
            )
            return repo.add_reading_pack(
                ReadingPackDraft(
                    recommendation_id=self.recommendation_id,
                    book_id=1,
                    artifact_id=artifact_id,
                    status="generated",
                    route="reading.deep_read_pack",
                    schema_version="deep_read_pack_v2",
                    title="Test Book 快读包",
                    summary="系统化能力来自可靠反馈",
                    content={
                        "one_sentence_thesis": "系统化能力来自可靠反馈",
                        "book_positioning": "定位",
                        "expanded_argument": ["先识别问题", "再建立反馈"],
                        "part_walkthrough": [{"title_or_inferred_title": "第一部分", "what_happens": "说明问题", "key_claim": "反馈重要"}],
                        "concept_cards": [{"concept": "反馈闭环", "meaning": "持续校准"}],
                    },
                    generator_provider="hermes-agent",
                )
            )
        finally:
            conn.close()

    def _add_guided_reading_plan(self) -> int:
        source = Path(self.tmp.name) / "guided-source.md"
        source.write_text(
            "\n\n".join(
                [
                    "第一段先把问题抛出来。用户不是不想看书，而是没有耐心进入。",
                    "第二段说明导读应该像短视频一样先给钩子，但后面要接回原文。",
                    "第三段进入反馈。太长了就缩短，想继续就开放下一段。",
                    "第四段说明追剧式伴读要避免剧透，只能根据已读范围生成上一集回顾、今日看点和下一集悬念。",
                    "第五段强调第一版不要追求深度报告，而是先让用户愿意打开、读一点、反馈一下。",
                ]
            ),
            encoding="utf-8",
        )
        conn = connect(self.db_path)
        try:
            repo = Repository(conn)
            result = GuidedReadingService(repo, library_dir=self.library_dir).create_plan_from_source(
                source_path=source,
                title="低耐心阅读",
                plan_days=2,
                daily_minutes=8,
            )
            return result.first_day_id
        finally:
            conn.close()

    def _latest_feedback(self):
        conn = connect(self.db_path)
        try:
            return conn.execute("SELECT * FROM feedback_events ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
