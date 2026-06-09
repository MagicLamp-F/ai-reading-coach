import base64
import hashlib
import hmac
import unittest
import json

from app.http_client import HttpResponse
from app.reading_pack import ReadingPackPreview
from app.repository import RecommendationDraft
from app.lark import LarkRobotClient, generate_lark_sign


class ExplodingHttp:
    def post_json(self, url, payload):
        raise AssertionError("HTTP should not be called when Lark webhook is disabled")


class CapturingHttp:
    def __init__(self, responses=None):
        self.payload = None
        self.calls = 0
        self.responses = responses or [HttpResponse(status=200, body={"code": 0, "data": {"message_id": "mid"}})]

    def post_json(self, url, payload):
        self.payload = payload
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class LarkTests(unittest.TestCase):
    def test_generate_lark_sign_uses_timestamp_newline_secret(self):
        expected = base64.b64encode(
            hmac.new(
                b"1234567890\nsecret",
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        self.assertEqual(generate_lark_sign(1234567890, "secret"), expected)

    def test_send_text_is_noop_when_disabled(self):
        client = LarkRobotClient(webhook_url="", webhook_secret="", http=ExplodingHttp())

        self.assertIsNone(client.send_text("hello"))

    def test_recommendation_card_shows_hypothesis_dimensions_and_feedback_buttons(self):
        http = CapturingHttp()
        client = LarkRobotClient(webhook_url="https://example.test/webhook", webhook_secret="", http=http)
        draft = RecommendationDraft(
            title="Test Book",
            author="A",
            source_url="https://example.test/book",
            slot_type="profile_fit",
            theme="软件工程实践",
            recommendation_reason="推荐理由",
            profile_mapping="画像映射",
            system_hypothesis="测试用户是否需要系统设计基础",
            profile_dimensions=["knowledge_gap", "system_reliability"],
            expected_benefit="可能收益",
            risk="篇幅较长",
            reading_suggestion="建议读法",
            metadata={},
        )

        message_id = client.send_recommendation(
            1,
            1,
            draft,
            [
                type("Link", (), {"feedback_type": "like", "url": "https://example.test/fb/like"}),
                type("Link", (), {"feedback_type": "neutral", "url": "https://example.test/fb/neutral"}),
                type("Link", (), {"feedback_type": "not_interested", "url": "https://example.test/fb/not_interested"}),
                type("Link", (), {"feedback_type": "already_read", "url": "https://example.test/fb/already_read"}),
                type("Link", (), {"feedback_type": "go_deeper", "url": "https://example.test/fb/go_deeper"}),
            ],
        )

        self.assertEqual(message_id, "mid")
        card = http.payload["card"]
        rendered = "\n".join(
            element["text"]["content"]
            for element in card["elements"]
            if element.get("tag") == "div"
        )
        self.assertIn("**系统假设**：测试用户是否需要系统设计基础", rendered)
        self.assertIn("**测试画像维度**：knowledge_gap、system_reliability", rendered)
        self.assertIn("**推荐理由**：推荐理由", rendered)
        self.assertIn("**可能不适合的原因**：篇幅较长", rendered)
        actions = next(element["actions"] for element in card["elements"] if element.get("tag") == "action")
        self.assertEqual(len(actions), 5)
        self.assertEqual(
            {action["url"].rsplit("/", 1)[-1] for action in actions},
            {"like", "neutral", "not_interested", "already_read", "go_deeper"},
        )

    def test_profile_test_summary_card_shows_hypotheses_dimensions_and_feedback_reminder(self):
        http = CapturingHttp()
        client = LarkRobotClient(webhook_url="https://example.test/webhook", webhook_secret="", http=http)
        drafts = [
            RecommendationDraft(
                title=f"Book {index}",
                author="A",
                source_url="",
                slot_type="profile_fit",
                theme="软件工程实践",
                recommendation_reason="r",
                profile_mapping="m",
                system_hypothesis=f"假设 {index}",
                profile_dimensions=["knowledge_gap", "system_reliability"] if index == 1 else ["knowledge_gap", "reading_preference"],
                expected_benefit="b",
                risk="risk",
                reading_suggestion="s",
                metadata={},
            )
            for index in range(1, 4)
        ]

        message_id = client.send_profile_test_summary(drafts)

        self.assertEqual(message_id, "mid")
        card = http.payload["card"]
        self.assertEqual(card["header"]["title"]["content"], "今日画像测试")
        rendered = "\n".join(
            element["text"]["content"]
            for element in card["elements"]
            if element.get("tag") == "div"
        )
        self.assertIn("今天测试的 3 个 system_hypothesis", rendered)
        self.assertIn("1. 假设 1", rendered)
        self.assertIn("2. 假设 2", rendered)
        self.assertIn("3. 假设 3", rendered)
        self.assertIn("knowledge_gap、system_reliability、reading_preference", rendered)
        self.assertIn("帮助系统验证这些假设", rendered)

    def test_recommendation_card_can_include_reading_pack_preview(self):
        http = CapturingHttp()
        client = LarkRobotClient(webhook_url="https://example.test/webhook", webhook_secret="", http=http)
        draft = RecommendationDraft(
            title="Test Book",
            author="A",
            source_url="",
            slot_type="profile_fit",
            theme="软件工程实践",
            recommendation_reason="推荐理由",
            profile_mapping="画像映射",
            system_hypothesis="测试假设",
            profile_dimensions=["knowledge_gap"],
            expected_benefit="可能收益",
            risk="篇幅较长",
            reading_suggestion="建议读法",
            metadata={},
        )

        client.send_recommendation(
            1,
            1,
            draft,
            [type("Link", (), {"feedback_type": "like", "url": "https://example.test/fb/like"})],
            ReadingPackPreview(
                summary="这本书讲如何搭建可靠系统。",
                ten_min_route="先读核心论点和章节地图。",
                core_points=("先明确问题", "再形成反馈闭环"),
                concepts=("可靠性", "反馈闭环"),
                chapter_items=("第一部分：问题", "第二部分：方法"),
                examples=("用运行日志定位问题",),
                limitations=("需要人工校验公开来源",),
                source_status="source_limited",
                source_coverage_score=0.35,
                source_count=1,
                artifact_path="library/2026/05/test/reading-pack.md",
                status="fallback",
                reading_pack_url="https://example.test/reading-pack?id=1&token=t",
            ),
        )

        rendered = "\n".join(
            element["text"]["content"]
            for element in http.payload["card"]["elements"]
            if element.get("tag") == "div"
        )
        self.assertIn("快读包", rendered)
        self.assertIn("[打开完整快读包](https://example.test/reading-pack?id=1&token=t)", rendered)
        self.assertNotIn("来源质量", rendered)
        self.assertNotIn("这本书讲如何搭建可靠系统", rendered)
        self.assertNotIn("核心概念", rendered)
        self.assertNotIn("章节/部分 walkthrough", rendered)
        self.assertNotIn("例子/案例", rendered)
        self.assertNotIn("library/2026/05/test/reading-pack.md", rendered)

    def test_can_send_standalone_reading_pack_preview_card(self):
        http = CapturingHttp()
        client = LarkRobotClient(webhook_url="https://example.test/webhook", webhook_secret="", http=http)

        message_id = client.send_reading_pack_preview(
            ReadingPackPreview(
                summary="这本书讲如何搭建可靠系统。",
                ten_min_route="先读核心论点和章节地图。",
                core_points=("先明确问题",),
                concepts=("可靠性",),
                chapter_items=("第一部分：问题",),
                examples=("用运行日志定位问题",),
                limitations=("需要人工校验公开来源",),
                source_status="source_limited",
                source_coverage_score=0.35,
                source_count=1,
                artifact_path="library/2026/05/test/reading-pack.md",
                status="generated",
                reading_pack_url="https://example.test/reading-pack?id=2&token=t",
            )
        )

        self.assertEqual(message_id, "mid")
        self.assertEqual(http.payload["card"]["header"]["title"]["content"], "深度读完包")
        rendered = "\n".join(
            element["text"]["content"]
            for element in http.payload["card"]["elements"]
            if element.get("tag") == "div"
        )
        self.assertIn("快读包", rendered)
        self.assertIn("[打开完整快读包](https://example.test/reading-pack?id=2&token=t)", rendered)
        self.assertNotIn("机器归档", rendered)
        self.assertNotIn("这本书讲如何搭建可靠系统", rendered)

    def test_can_send_guided_reading_day_card(self):
        http = CapturingHttp()
        client = LarkRobotClient(webhook_url="https://example.test/webhook", webhook_secret="", http=http)
        row = {
            "book_title": "低耐心阅读",
            "day_number": 1,
            "plan_days": 5,
            "estimated_minutes": 8,
            "mode": "drama",
            "spoiler_policy": "avoid",
            "content_json": json.dumps(
                {
                    "hook": "上一集先续上。",
                    "one_question": "人物关系发生了什么变化？",
                    "tomorrow_teaser": "下一段继续看冲突怎么推进。",
                },
                ensure_ascii=False,
            ),
        }

        message_id = client.send_guided_reading_day(row, "https://example.test/guided")

        self.assertEqual(message_id, "mid")
        self.assertEqual(http.payload["card"]["header"]["title"]["content"], "今日导读")
        rendered = "\n".join(
            element["text"]["content"]
            for element in http.payload["card"]["elements"]
            if element.get("tag") == "div"
        )
        self.assertIn("低耐心阅读", rendered)
        self.assertIn("追剧式伴读", rendered)
        self.assertIn("不剧透：开启", rendered)
        self.assertIn("上一集先续上", rendered)
        actions = next(element["actions"] for element in http.payload["card"]["elements"] if element.get("tag") == "action")
        self.assertEqual(actions[0]["url"], "https://example.test/guided")

    def test_send_retries_lark_frequency_limit_then_succeeds(self):
        sleeps = []
        http = CapturingHttp(
            [
                HttpResponse(status=200, body={"code": 11232, "msg": "frequency limited"}),
                HttpResponse(status=200, body={"code": 0, "data": {"message_id": "mid-after-retry"}}),
            ]
        )
        client = LarkRobotClient(
            webhook_url="https://example.test/webhook",
            webhook_secret="",
            http=http,
            retry_base_seconds=0.5,
            rate_limit_cooldown_seconds=30,
            sleeper=sleeps.append,
        )

        self.assertEqual(client.send_text("hello"), "mid-after-retry")
        self.assertEqual(http.calls, 2)
        self.assertEqual(sleeps, [30])

    def test_send_stops_after_three_temporary_failures(self):
        sleeps = []
        http = CapturingHttp(
            [
                HttpResponse(status=500, body={"code": 500, "msg": "temporary"}),
                HttpResponse(status=500, body={"code": 500, "msg": "temporary"}),
                HttpResponse(status=500, body={"code": 500, "msg": "temporary"}),
            ]
        )
        client = LarkRobotClient(
            webhook_url="https://example.test/webhook",
            webhook_secret="",
            http=http,
            retry_base_seconds=1,
            sleeper=sleeps.append,
        )

        self.assertIsNone(client.send_text("hello"))
        self.assertEqual(http.calls, 3)
        self.assertEqual(sleeps, [1, 2])


if __name__ == "__main__":
    unittest.main()
