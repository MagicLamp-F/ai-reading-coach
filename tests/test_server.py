import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from app.db import connect, init_db
from app.feedback import build_feedback_url, build_reading_pack_url, sign_feedback_free_text
from app.repository import ReadingPackDraft, RecommendationDraft, Repository
from app.server import FeedbackHandler


class FeedbackServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        conn = connect(self.db_path)
        init_db(conn)
        self.repo = Repository(conn)
        self.recommendation_id = self._add_recommendation()
        conn.close()

        self.settings = SimpleNamespace(database_path=self.db_path, feedback_secret="secret", public_base_url="")
        handler = type("TestFeedbackHandler", (FeedbackHandler,), {"settings": self.settings})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        host, port = self.server.server_address
        self.settings.public_base_url = f"http://{host}:{port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.tmp.cleanup()

    def test_feedback_without_reason_returns_reason_selection_page(self):
        url = build_feedback_url(self.settings.public_base_url, self.recommendation_id, "not_interested", self.settings.feedback_secret)

        with urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("选择“不感兴趣”的原因", body)
        self.assertIn("topic_irrelevant", body)
        self.assertIn("already_know", body)
        self.assertEqual(self._feedback_count(), 0)

    def test_feedback_with_reason_records_event(self):
        url = build_feedback_url(
            self.settings.public_base_url,
            self.recommendation_id,
            "not_interested",
            self.settings.feedback_secret,
            reason_code="already_know",
        )

        with urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("已记录", body)
        self.assertIn("name=\"free_text\"", body)
        self.assertIn("maxlength=\"500\"", body)
        row = self._latest_feedback()
        self.assertEqual(row["feedback_type"], "not_interested")
        self.assertEqual(row["reason_code"], "already_know")

    def test_feedback_free_text_updates_same_event_and_escapes_preview(self):
        self._record_feedback_with_reason("already_know")
        feedback_id = int(self._latest_feedback()["id"])
        body = self._post_free_text(feedback_id, "<script>alert(1)</script>")

        row = self._latest_feedback()
        self.assertEqual(row["id"], feedback_id)
        self.assertEqual(row["free_text"], "<script>alert(1)</script>")
        self.assertIn("补充内容已更新", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertNotIn("<script>alert(1)</script>", body)

    def test_feedback_free_text_is_limited_to_500_chars(self):
        self._record_feedback_with_reason("already_know")
        feedback_id = int(self._latest_feedback()["id"])
        self._post_free_text(feedback_id, "x" * 600)

        row = self._latest_feedback()
        self.assertEqual(len(row["free_text"]), 500)

    def test_feedback_free_text_rejects_tampered_signature(self):
        self._record_feedback_with_reason("already_know")
        feedback_id = int(self._latest_feedback()["id"])

        with self.assertRaises(HTTPError) as ctx:
            self._post_free_text(feedback_id, "hello", token="bad-token")

        self.assertEqual(ctx.exception.code, 403)

    def test_reading_pack_page_renders_content_and_feedback_links(self):
        reading_pack_id = self._add_reading_pack()
        url = build_reading_pack_url(self.settings.public_base_url, reading_pack_id, self.settings.feedback_secret)

        with urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Test Book 快读包", body)
        self.assertIn("一句话主张", body)
        self.assertIn("系统化能力来自可靠反馈", body)
        self.assertIn("全书总览", body)
        self.assertIn("本页导读", body)
        self.assertIn("页内目录", body)
        self.assertIn("overflow-x:hidden", body)
        self.assertIn("text-overflow:ellipsis", body)
        self.assertIn(".feedbacks{position:static", body)
        self.assertIn("class=\"text-paragraph\"", body)
        self.assertIn("约 1 分钟", body)
        self.assertIn("scrollBar", body)
        self.assertIn("阅读进度", body)
        self.assertIn("完整论证链和心智模型", body)
        self.assertIn("喜欢", body)
        self.assertIn("/feedback/inline", body)
        self.assertIn("reason_choice", body)

    def test_reading_pack_page_can_open_specific_module(self):
        reading_pack_id = self._add_reading_pack()
        url = build_reading_pack_url(self.settings.public_base_url, reading_pack_id, self.settings.feedback_secret)

        with urlopen(f"{url}&module=argument", timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("论证 2/5", body)
        self.assertIn("论证链", body)
        self.assertIn("toc-card active", body)
        self.assertIn("argument-1", body)
        self.assertIn("class=\"li-part\"", body)
        self.assertIn("读完带走", body)
        self.assertIn("上一页：总览", body)
        self.assertIn("下一页：章节", body)
        self.assertIn("按章节/部分穿过全书结构", body)

    def test_inline_feedback_records_reason_and_free_text(self):
        reading_pack_id = self._add_reading_pack()
        page_url = build_reading_pack_url(self.settings.public_base_url, reading_pack_id, self.settings.feedback_secret)
        body = self._post_inline_feedback("like", "topic_matches", "正好需要", page_url)

        row = self._latest_feedback()
        self.assertEqual(row["feedback_type"], "like")
        self.assertEqual(row["reason_code"], "topic_matches")
        self.assertEqual(row["free_text"], "正好需要")
        self.assertIn("反馈已记录", body)
        self.assertIn("回到快读包", body)

    def test_reading_pack_page_rejects_bad_signature(self):
        reading_pack_id = self._add_reading_pack()
        url = f"{self.settings.public_base_url}/reading-pack?id={reading_pack_id}&token=bad"

        with self.assertRaises(HTTPError) as ctx:
            urlopen(url, timeout=5)

        self.assertEqual(ctx.exception.code, 403)

    def test_feedback_with_tampered_reason_signature_is_rejected(self):
        valid = build_feedback_url(
            self.settings.public_base_url,
            self.recommendation_id,
            "not_interested",
            self.settings.feedback_secret,
            reason_code="already_know",
        )
        tampered = valid.replace("already_know", "too_hard")

        with self.assertRaises(HTTPError) as ctx:
            urlopen(tampered, timeout=5)

        self.assertEqual(ctx.exception.code, 403)
        self.assertEqual(self._feedback_count(), 0)

    def _record_feedback_with_reason(self, reason_code: str) -> None:
        url = build_feedback_url(
            self.settings.public_base_url,
            self.recommendation_id,
            "not_interested",
            self.settings.feedback_secret,
            reason_code=reason_code,
        )
        with urlopen(url, timeout=5):
            pass

    def _post_free_text(self, feedback_id: int, free_text: str, token: str | None = None) -> str:
        payload = urlencode(
            {
                "feedback_id": str(feedback_id),
                "token": token or sign_feedback_free_text(feedback_id, self.settings.feedback_secret),
                "free_text": free_text,
            }
        ).encode("utf-8")
        req = Request(
            f"{self.settings.public_base_url}/feedback/free-text",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(req, timeout=5) as response:
            return response.read().decode("utf-8")

    def _post_inline_feedback(self, feedback_type: str, reason_code: str, free_text: str, return_url: str) -> str:
        from app.feedback import sign_feedback

        token = sign_feedback(self.recommendation_id, feedback_type, self.settings.feedback_secret, reason_code)
        payload = urlencode(
            {
                "recommendation_id": str(self.recommendation_id),
                "feedback_type": feedback_type,
                "reason_choice": f"{reason_code}.{token}",
                "free_text": free_text,
                "return_url": return_url,
            }
        ).encode("utf-8")
        req = Request(
            f"{self.settings.public_base_url}/feedback/inline",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(req, timeout=5) as response:
            return response.read().decode("utf-8")

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

    def _feedback_count(self) -> int:
        conn = connect(self.db_path)
        try:
            return int(conn.execute("SELECT COUNT(*) AS c FROM feedback_events").fetchone()["c"])
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
