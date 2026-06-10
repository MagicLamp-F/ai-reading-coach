import tempfile
import unittest
from pathlib import Path

from app.db import connect, init_db
from app.repository import RecommendationDraft, Repository
from app.workflow import ReadingCoachWorkflow


class FakeLark:
    def __init__(self):
        self.sent_texts = []

    def send_text(self, text):
        self.sent_texts.append(text)
        return "weekly-message-id"


class WeeklyReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "test.db")
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.lark = FakeLark()
        self.workflow = ReadingCoachWorkflow(
            repo=self.repo,
            search=None,
            llm=None,
            lark=self.lark,
            telegram=None,
            channel="lark",
            public_base_url="https://example.test",
            feedback_secret="secret",
            max_search_calls=0,
            max_model_calls=0,
        )

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_weekly_report_with_feedback(self):
        rec_id = self._add_recommendation(
            theme="软件工程实践",
            slot_type="profile_fit",
            profile_dimensions=["knowledge_gap", "system_reliability"],
        )
        self.repo.add_feedback(rec_id, "like", reason_code="useful_methodology")
        self.repo.add_feedback(rec_id, "go_deeper", reason_code="knowledge_gap")
        self.repo.upsert_profile_item(
            "knowledge_gap",
            "软件工程实践",
            0.16,
            0.10,
            {"source": "test", "text": "画像测试证据"},
        )

        report = self.workflow.build_weekly_report()

        self.assertIn("一、本周推荐概况", report)
        self.assertIn("给你的结论", report)
        self.assertIn("画像写回状态", report)
        self.assertIn("推荐总数：1", report)
        self.assertIn("反馈总数：2", report)
        self.assertIn("正反馈数量：2", report)
        self.assertIn("ARC structured profile：本周 2 条反馈中，已处理 0 条，待处理 2 条。", report)
        self.assertIn("Hermes native USER profile：没有查到 feedback.ingest 审计记录", report)
        self.assertIn("喜欢 (like): 1", report)
        self.assertIn("想深入 (go_deeper): 1", report)
        self.assertIn("方法论有用 (useful_methodology): 1", report)
        self.assertIn("明确知识缺口 (knowledge_gap): 1", report)
        self.assertIn("知识缺口 / 喜欢: 1", report)
        self.assertIn("三、画像置信度分层", report)
        self.assertIn("待验证画像", report)
        self.assertIn("category=知识缺口; content=软件工程实践", report)
        self.assertIn("confidence=0.40; evidence_count=1", report)
        self.assertIn("最近证据=test:画像测试证据", report)
        self.assertIn("八、需要你回答的 3 个反思问题", report)

    def test_weekly_report_without_feedback_has_empty_state(self):
        report = self.workflow.build_weekly_report()

        self.assertIn("推荐总数：0", report)
        self.assertIn("反馈总数：0", report)
        self.assertIn("本周没有 feedback 事件，所以没有发生“反馈驱动”的 ARC structured profile 写回。", report)
        self.assertIn("Hermes 主画像也没有收到 feedback.ingest 写回请求", report)
        self.assertIn("暂无反馈", report)
        self.assertIn("暂无原因反馈", report)
        self.assertIn("暂无稳定画像", report)
        self.assertIn("最近 7 天暂无新画像信号", report)
        self.assertIn("暂无自由文本补充", report)
        self.assertIn("本周暂无反馈，应先降低推荐假设复杂度", report)

    def test_reason_code_enters_misunderstanding_section(self):
        rec_id = self._add_recommendation(theme="个人知识管理", slot_type="exploration")
        self.repo.add_feedback(rec_id, "not_interested", reason_code="too_theoretical")

        report = self.workflow.build_weekly_report()

        self.assertIn("太理论 (too_theoretical): 1", report)
        self.assertIn("个人知识管理", report)
        self.assertIn("太理论，应该增加实践案例", report)

    def test_weekly_report_splits_profile_confidence_layers(self):
        for index in range(3):
            self.repo.upsert_profile_item(
                "long_term_interest",
                "AI Agent 商业化",
                0.10,
                0.10,
                {"source": "test", "text": f"稳定证据 {index + 1}"},
            )
        self.repo.upsert_profile_item(
            "short_term_interest",
            "软件工程实践",
            0.10,
            0.08,
            {"source": "test", "text": "待验证证据"},
        )
        self.repo.upsert_profile_item(
            "disliked_topic",
            "短期避免：个人知识管理",
            0.10,
            0.08,
            {"source": "test", "text": "误解候选证据"},
        )
        rec_id = self._add_recommendation(theme="个人知识管理", slot_type="profile_fit")
        self.repo.add_feedback(rec_id, "not_interested", reason_code="wrong_timing")

        report = self.workflow.build_weekly_report()

        self.assertIn("稳定画像\n- category=长期兴趣; content=AI Agent 商业化; confidence=0.60; evidence_count=3", report)
        self.assertIn("待验证画像", report)
        self.assertIn("category=短期关注; content=软件工程实践; confidence=0.38; evidence_count=1", report)
        self.assertIn("新出现信号", report)
        self.assertIn("category=反感主题; content=短期避免：个人知识管理", report)
        self.assertIn("可能误解", report)
        self.assertIn("误解信号=个人知识管理 / 时机不对 x1", report)

    def test_weekly_report_flags_profiles_with_multiple_negative_feedback(self):
        self.repo.upsert_profile_item(
            "disliked_topic",
            "短期避免：数据库系统",
            0.10,
            0.08,
            {"source": "test", "text": "负反馈聚合候选"},
        )
        rec_id = self._add_recommendation(theme="数据库系统", slot_type="profile_fit")
        self.repo.add_feedback(rec_id, "not_interested", reason_code="already_know")
        self.repo.add_feedback(rec_id, "not_interested", reason_code="too_hard")

        report = self.workflow.build_weekly_report()

        self.assertIn("可能误解", report)
        self.assertIn("category=反感主题; content=短期避免：数据库系统", report)
        self.assertIn("误解信号=数据库系统 / 已经掌握 x1", report)

    def test_weekly_report_includes_recent_three_free_text_summaries_escaped(self):
        for index in range(4):
            rec_id = self._add_recommendation(theme=f"主题{index}", slot_type="profile_fit")
            self.repo.add_feedback(
                rec_id,
                "not_interested",
                reason_code="too_theoretical",
                free_text=f"<b>补充 {index}</b>",
            )

        report = self.workflow.build_weekly_report()

        self.assertIn("六、最近自由文本补充", report)
        self.assertIn("主题3 / 不感兴趣 / 太理论: &lt;b&gt;补充 3&lt;/b&gt;", report)
        self.assertIn("主题2 / 不感兴趣 / 太理论: &lt;b&gt;补充 2&lt;/b&gt;", report)
        self.assertIn("主题1 / 不感兴趣 / 太理论: &lt;b&gt;补充 1&lt;/b&gt;", report)
        self.assertNotIn("主题0 / 不感兴趣", report)
        self.assertNotIn("<b>补充", report)

    def test_send_weekly_report_uses_lark(self):
        self.workflow.send_weekly_report()

        self.assertEqual(len(self.lark.sent_texts), 1)
        self.assertIn("7 天画像复盘", self.lark.sent_texts[0])
        row = self.conn.execute(
            "SELECT status FROM run_logs WHERE run_type = ? ORDER BY id DESC LIMIT 1",
            ("weekly_report",),
        ).fetchone()
        self.assertEqual(row["status"], "success")

    def _add_recommendation(
        self,
        theme: str,
        slot_type: str = "profile_fit",
        profile_dimensions: list[str] | None = None,
    ) -> int:
        run_id = self.repo.create_run("test")
        return self.repo.add_recommendation(
            run_id,
            RecommendationDraft(
                title="Test Book",
                author="A",
                source_url="",
                slot_type=slot_type,
                theme=theme,
                recommendation_reason="r",
                profile_mapping="m",
                system_hypothesis=f"测试用户是否关注 {theme}",
                profile_dimensions=profile_dimensions or ["long_term_interest"],
                expected_benefit="b",
                risk="risk",
                reading_suggestion="s",
                metadata={},
            ),
            __import__("datetime").date.today(),
        )


if __name__ == "__main__":
    unittest.main()
