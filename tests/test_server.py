import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from app.db import connect, init_db
from app.feedback import build_feedback_url, build_guided_reading_day_url, build_reading_pack_url, sign_feedback_free_text
from app.guided_reading import GuidedReadingService
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
        self.assertIn(".feedbacks{width:100%", body)
        self.assertIn("class=\"text-paragraph\"", body)
        self.assertIn("约 1 分钟", body)
        self.assertIn("scrollBar", body)
        self.assertIn("阅读进度", body)
        self.assertIn("完整论证链和心智模型", body)
        self.assertIn("喜欢", body)
        self.assertIn("/feedback/inline", body)
        self.assertIn("reason_choice", body)
        self.assertIn("我的摘抄", body)
        self.assertIn("/reading-pack/quote", body)
        self.assertIn("fillQuote", body)

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

    def test_reading_pack_quote_records_quote_and_profile_signal(self):
        reading_pack_id = self._add_reading_pack()
        page_url = build_reading_pack_url(self.settings.public_base_url, reading_pack_id, self.settings.feedback_secret)
        body = self._post_reading_quote(page_url, "这是一句想反复回味的原著句子", "语言很有画面感")

        self.assertIn("我的摘抄", body)
        self.assertIn("这是一句想反复回味的原著句子", body)
        conn = connect(self.db_path)
        try:
            quote = conn.execute("SELECT * FROM reading_quotes ORDER BY id DESC LIMIT 1").fetchone()
            profile = conn.execute(
                "SELECT * FROM profile_items WHERE evidence_json LIKE ? ORDER BY id DESC LIMIT 1",
                (f'%\"quote_id\": {int(quote["id"])}%',),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(quote["selected_text"], "这是一句想反复回味的原著句子")
        self.assertEqual(quote["note"], "语言很有画面感")
        self.assertIsNotNone(profile)

    def test_reading_pack_page_rejects_bad_signature(self):
        reading_pack_id = self._add_reading_pack()
        url = f"{self.settings.public_base_url}/reading-pack?id={reading_pack_id}&token=bad"

        with self.assertRaises(HTTPError) as ctx:
            urlopen(url, timeout=5)

        self.assertEqual(ctx.exception.code, 403)

    def test_guided_reading_page_renders_hook_source_and_feedback(self):
        day_id = self._add_guided_reading_plan()
        url = build_guided_reading_day_url(self.settings.public_base_url, day_id, self.settings.feedback_secret)

        with urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Day 1/2", body)
        self.assertIn("今日钩子", body)
        self.assertIn("今天只抓一个问题", body)
        self.assertIn("今日原文", body)
        self.assertIn("白话拆解", body)
        self.assertIn("/guided-reading/feedback", body)
        self.assertIn("太长了", body)
        self.assertIn("想继续", body)

    def test_guided_reading_feedback_records_progress_event(self):
        day_id = self._add_guided_reading_plan()
        token = build_guided_reading_day_url("", day_id, self.settings.feedback_secret).split("token=", 1)[1]
        payload = urlencode(
            {
                "day_id": str(day_id),
                "token": token,
                "event_type": "too_long",
                "note": "今天读不动",
            }
        ).encode("utf-8")
        req = Request(
            f"{self.settings.public_base_url}/guided-reading/feedback",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        with urlopen(req, timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("导读反馈已记录", body)
        conn = connect(self.db_path)
        try:
            row = conn.execute("SELECT * FROM reading_progress_events ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(row["event_type"], "too_long")
            self.assertIn("今天读不动", row["detail_json"])
        finally:
            conn.close()

    def test_guided_reading_page_rejects_bad_signature(self):
        day_id = self._add_guided_reading_plan()

        with self.assertRaises(HTTPError) as ctx:
            urlopen(f"{self.settings.public_base_url}/guided-reading?day_id={day_id}&token=bad", timeout=5)

        self.assertEqual(ctx.exception.code, 403)

    def test_guided_reading_plans_page_can_create_plan_with_lark_push(self):
        admin_token = sign_feedback_free_text(0, self.settings.feedback_secret)
        payload = urlencode(
            {
                "admin_token": admin_token,
                "title": "页面配置书",
                "author": "A",
                "plan_days": "2",
                "daily_minutes": "8",
                "mode": "drama",
                "tone": "drama",
                "spoiler_policy": "avoid",
                "lark_push_enabled": "1",
                "source_text": "\n\n".join(
                    [
                        "第一段说明页面可以配置阅读计划，而且需要足够简单。用户打开业务系统后，应该能直接粘贴书源、选择天数和每天分钟数。",
                        "第二段说明飞书推送应该是每本书独立开关，不应该全局强制开启。这样不同书可以有不同提醒策略。",
                        "第三段说明追剧式伴读要避免剧透，并且只根据已读范围生成提示。系统不能提前揭示未读剧情。",
                        "第四段说明用户反馈会影响后续计划。太长了就缩短，想继续就开放下一段，刚刚好就保持密度。",
                    ]
                ),
            }
        ).encode("utf-8")
        req = Request(
            f"{self.settings.public_base_url}/guided-reading/plans",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        with urlopen(req, timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("阅读计划已创建", body)
        conn = connect(self.db_path)
        try:
            row = conn.execute("SELECT * FROM reading_plans ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(row["title"], "页面配置书")
            self.assertEqual(row["mode"], "drama")
            self.assertEqual(int(row["lark_push_enabled"]), 1)
        finally:
            conn.close()

    def test_guided_reading_plans_page_rejects_bad_admin_token(self):
        with self.assertRaises(HTTPError) as ctx:
            urlopen(f"{self.settings.public_base_url}/guided-reading/plans?admin_token=bad", timeout=5)

        self.assertEqual(ctx.exception.code, 403)

    def test_guided_reading_sources_upload_detail_create_and_delete(self):
        admin_token = sign_feedback_free_text(0, self.settings.feedback_secret)
        boundary = "----arc" + uuid.uuid4().hex
        source_text = "\n\n".join(
            [
                "第一段说明导入书源需要支持文件上传，而不是只能粘贴文本。用户可以上传 UTF-8 的 md 或 txt 文件。",
                "第二段说明导入后需要管理入口，可以查看书源、基于书源创建计划，也可以删除不再使用的书源。",
                "第三段说明第一版不支持 PDF 和 EPUB，因为解析质量和章节切分会明显复杂。",
                "第四段说明上传限制必须保守，先限制文件大小和格式，避免业务系统暴露过大的输入面。",
            ]
        )
        body = self._multipart_body(
            boundary,
            {
                "admin_token": admin_token,
                "title": "上传书源",
                "author": "A",
            },
            {"source_file": ("source.txt", source_text.encode("utf-8"), "text/plain")},
        )
        req = Request(
            f"{self.settings.public_base_url}/guided-reading/sources/upload",
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

        with urlopen(req, timeout=5) as response:
            uploaded = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("书源已导入", uploaded)
        conn = connect(self.db_path)
        try:
            source = conn.execute("SELECT * FROM reading_source_files ORDER BY id DESC LIMIT 1").fetchone()
            source_id = int(source["id"])
            self.assertEqual(source["title"], "上传书源")
            self.assertEqual(source["file_format"], "txt")
        finally:
            conn.close()

        detail_url = f"{self.settings.public_base_url}/guided-reading/source?id={source_id}&admin_token={admin_token}"
        with urlopen(detail_url, timeout=5) as response:
            detail = response.read().decode("utf-8")
        self.assertIn("内容预览", detail)
        self.assertIn("基于此书源创建计划", detail)

        payload = urlencode(
            {
                "admin_token": admin_token,
                "source_file_id": str(source_id),
                "title": "上传书源",
                "plan_days": "2",
                "daily_minutes": "8",
                "mode": "guided",
                "tone": "short_video",
                "spoiler_policy": "avoid",
            }
        ).encode("utf-8")
        req = Request(
            f"{self.settings.public_base_url}/guided-reading/plans",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(req, timeout=5) as response:
            created = response.read().decode("utf-8")
        self.assertIn("阅读计划已创建", created)

        payload = urlencode({"admin_token": admin_token, "source_file_id": str(source_id)}).encode("utf-8")
        req = Request(
            f"{self.settings.public_base_url}/guided-reading/sources/delete",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(req, timeout=5) as response:
            deleted = response.read().decode("utf-8")
        self.assertIn("书源已删除", deleted)

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

    def _post_reading_quote(self, page_url: str, selected_text: str, note: str) -> str:
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(page_url).query)
        payload = urlencode(
            {
                "reading_pack_id": query["id"][0],
                "token": query["token"][0],
                "module": "overview",
                "section_title": "一句话主张",
                "selected_text": selected_text,
                "note": note,
            }
        ).encode("utf-8")
        req = Request(
            f"{self.settings.public_base_url}/reading-pack/quote",
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
            result = GuidedReadingService(repo, library_dir=Path(self.tmp.name) / "library").create_plan_from_source(
                source_path=source,
                title="低耐心阅读",
                plan_days=2,
                daily_minutes=8,
            )
            return result.first_day_id
        finally:
            conn.close()

    def _multipart_body(self, boundary: str, fields: dict, files: dict) -> bytes:
        chunks = []
        for name, value in fields.items():
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            chunks.append(str(value).encode("utf-8"))
            chunks.append(b"\r\n")
        for name, (filename, content, content_type) in files.items():
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode("utf-8")
            )
            chunks.append(content)
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks)

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
