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
from app.feedback import build_feedback_url, sign_feedback_free_text
from app.repository import RecommendationDraft, Repository
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
