import json
import tempfile
import unittest
from pathlib import Path

from app.db import connect, init_db
from app.reflection import (
    HermesReflectionService,
    ReflectionError,
    build_reflection_context,
    build_reflection_prompt,
)
from app.reflection_adapter import ReflectionAdapterError, ReflectionAgentResult
from app.repository import RecommendationDraft, Repository


class FakeLLM:
    api_key = "test-key"
    model = "test-model"

    def __init__(self, response=None):
        self.response = response or reflection_response()
        self.calls = []

    def complete_json(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        return self.response


class FailingLLM:
    api_key = "test-key"
    model = "test-model"

    def complete_json(self, system_prompt, user_prompt):
        raise RuntimeError("model unavailable")


class CapturingLark:
    def __init__(self, message_id="lark-message-id"):
        self.texts = []
        self.message_id = message_id

    def enabled(self):
        return True

    def send_text(self, text):
        self.texts.append(text)
        return self.message_id


class FakeAdapter:
    name = "fake-agent"

    def __init__(self, response=None):
        self.response = response or reflection_response()
        self.calls = []

    def generate_reflection(self, system_prompt, user_prompt, context):
        self.calls.append((system_prompt, user_prompt, context))
        return ReflectionAgentResult(
            response=self.response,
            provider=self.name,
            api_calls=0,
        )


class WarningAdapter(FakeAdapter):
    name = "fake-agent+fallback:custom"

    def generate_reflection(self, system_prompt, user_prompt, context):
        self.calls.append((system_prompt, user_prompt, context))
        return ReflectionAgentResult(
            response=self.response,
            provider="custom",
            api_calls=1,
            fallback_used=True,
            warnings=("fake-agent failed; fell back to custom: timeout",),
        )


class FailingAdapter:
    name = "failing-agent"

    def generate_reflection(self, system_prompt, user_prompt, context):
        raise ReflectionAdapterError("agent unavailable")


class ReflectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conn = connect(self.root / "test.db")
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.memory_dir = self.root / "memory"

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_reflection_context_contains_recommendations_feedback_reason_and_weekly_report(self):
        rec_id = self._add_recommendation(theme="AI Agent 商业化")
        self.repo.add_feedback(rec_id, "not_interested", reason_code="too_marketing", free_text="像广告")
        self.repo.upsert_profile_item(
            "reading_preference",
            "偏好一手资料",
            0.12,
            0.08,
            {"source": "test", "text": "用户明确反馈"},
        )

        context = build_reflection_context(self.repo, 7, "7 天画像复盘摘要")
        prompt = build_reflection_prompt(context)

        self.assertEqual(context["days"], 7)
        self.assertIn("AI Agent 商业化", prompt)
        self.assertIn("too_marketing", prompt)
        self.assertIn("像广告", prompt)
        self.assertIn("偏好一手资料", prompt)
        self.assertIn("7 天画像复盘摘要", prompt)

    def test_generate_reflection_saves_draft_markdown_and_lark_pending_review_summary(self):
        self._add_recommendation(theme="软件工程实践")
        llm = FakeLLM()
        lark = CapturingLark()
        service = HermesReflectionService(
            self.repo,
            llm,
            weekly_report_builder=lambda: "weekly report",
            lark=lark,
            memory_dir=self.memory_dir,
        )

        reflection_id = service.generate_reflection(days=7)

        row = self.repo.get_reflection(reflection_id)
        self.assertEqual(row["status"], "draft")
        self.assertIn("本周画像摘要", row["summary"])
        self.assertIn("稳定关注系统可靠性", row["accurate_observations_json"])
        markdown = (self.memory_dir / "reflections" / f"reflection_{reflection_id}.md").read_text(encoding="utf-8")
        self.assertIn("Hermes Reflection", markdown)
        self.assertIn("USER.md Patch", markdown)
        self.assertEqual(len(lark.texts), 1)
        self.assertIn("待人工确认", lark.texts[0])
        self.assertIn(f"reflection_id: {reflection_id}", lark.texts[0])

    def test_generate_reflection_can_use_agent_adapter_without_calling_llm(self):
        self._add_recommendation(theme="软件工程实践")
        llm = FakeLLM()
        adapter = FakeAdapter()
        service = HermesReflectionService(
            self.repo,
            llm,
            weekly_report_builder=lambda: "weekly report",
            memory_dir=self.memory_dir,
            adapter=adapter,
        )

        reflection_id = service.generate_reflection(days=7, notify_lark=False)

        row = self.repo.get_reflection(reflection_id)
        self.assertEqual(row["status"], "draft")
        self.assertEqual(llm.calls, [])
        self.assertEqual(len(adapter.calls), 1)
        self.assertIn("recommendations", adapter.calls[0][2])
        run = self.conn.execute(
            "SELECT * FROM run_logs WHERE run_type = 'hermes_reflection' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(run["api_calls"], 0)
        self.assertIn("fake-agent", run["metadata_json"])

    def test_agent_fallback_warning_is_recorded_without_apply(self):
        service = HermesReflectionService(
            self.repo,
            FakeLLM(),
            weekly_report_builder=lambda: "weekly report",
            memory_dir=self.memory_dir,
            adapter=WarningAdapter(),
        )

        reflection_id = service.generate_reflection(days=7, notify_lark=False)

        row = self.repo.get_reflection(reflection_id)
        self.assertEqual(row["status"], "draft")
        self.assertFalse((self.memory_dir / "USER.md").read_text(encoding="utf-8").strip().endswith("用户偏好工程实践与可落地方案。"))
        run = self.conn.execute(
            "SELECT * FROM run_logs WHERE run_type = 'hermes_reflection' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(run["status"], "success")
        self.assertIn("fell back to custom", run["warning_message"])

    def test_agent_failure_records_failed_run_without_reflection(self):
        service = HermesReflectionService(
            self.repo,
            FakeLLM(),
            weekly_report_builder=lambda: "weekly report",
            memory_dir=self.memory_dir,
            adapter=FailingAdapter(),
        )

        with self.assertRaises(ReflectionAdapterError):
            service.generate_reflection(days=7, notify_lark=False)

        run = self.conn.execute(
            "SELECT * FROM run_logs WHERE run_type = 'hermes_reflection' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        reflection_count = self.conn.execute("SELECT COUNT(*) AS count FROM reflections").fetchone()["count"]
        self.assertEqual(run["status"], "failed")
        self.assertIn("agent unavailable", run["error_message"])
        self.assertEqual(reflection_count, 0)

    def test_generate_reflection_treats_empty_lark_message_id_as_success(self):
        lark = CapturingLark(message_id="")
        service = HermesReflectionService(
            self.repo,
            FakeLLM(),
            weekly_report_builder=lambda: "weekly report",
            lark=lark,
            memory_dir=self.memory_dir,
        )

        service.generate_reflection(days=7)

        run = self.conn.execute(
            "SELECT * FROM run_logs WHERE run_type = 'hermes_reflection' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(run["status"], "success")
        self.assertIsNone(run["warning_message"])
        self.assertEqual(len(lark.texts), 1)

    def test_approve_and_apply_status_flow_appends_user_and_memory_files(self):
        service = HermesReflectionService(
            self.repo,
            FakeLLM(),
            weekly_report_builder=lambda: "weekly report",
            memory_dir=self.memory_dir,
        )
        reflection_id = service.generate_reflection(days=7, notify_lark=False)

        with self.assertRaises(ReflectionError):
            service.apply_reflection(reflection_id)

        service.approve_reflection(reflection_id)
        approved = self.repo.get_reflection(reflection_id)
        self.assertEqual(approved["status"], "approved")
        self.assertIsNotNone(approved["approved_at"])

        audit_path = service.apply_reflection(reflection_id)

        applied = self.repo.get_reflection(reflection_id)
        self.assertEqual(applied["status"], "applied")
        self.assertIsNotNone(applied["applied_at"])
        self.assertTrue(audit_path.exists())
        self.assertIn("Mode: manual", audit_path.read_text(encoding="utf-8"))
        user_md = (self.memory_dir / "USER.md").read_text(encoding="utf-8")
        memory_md = (self.memory_dir / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn(f"Reflection {reflection_id} Applied", user_md)
        self.assertIn("用户偏好工程实践", user_md)
        self.assertIn(f"Reflection {reflection_id} Applied", memory_md)
        self.assertIn("下周减少营销类内容", memory_md)

    def test_generate_reflection_auto_apply_writes_memory_and_change_log(self):
        lark = CapturingLark()
        service = HermesReflectionService(
            self.repo,
            FakeLLM(),
            weekly_report_builder=lambda: "weekly report",
            lark=lark,
            memory_dir=self.memory_dir,
        )

        reflection_id = service.generate_reflection(days=7, notify_lark=True, auto_apply=True)

        row = self.repo.get_reflection(reflection_id)
        self.assertEqual(row["status"], "applied")
        user_md = (self.memory_dir / "USER.md").read_text(encoding="utf-8")
        memory_md = (self.memory_dir / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("用户偏好工程实践", user_md)
        self.assertIn("下周减少营销类内容", memory_md)
        change_logs = list((self.memory_dir / "change_logs").glob(f"*_reflection_{reflection_id}_auto.md"))
        self.assertEqual(len(change_logs), 1)
        audit = change_logs[0].read_text(encoding="utf-8")
        self.assertIn("Mode: auto", audit)
        self.assertIn("USER.md Patch", audit)
        self.assertIn("MEMORY.md Patch", audit)
        self.assertEqual(len(lark.texts), 1)
        self.assertIn("已自动应用", lark.texts[0])
        self.assertNotIn("待人工确认", lark.texts[0])

    def test_llm_failure_records_failed_run_without_reflection(self):
        service = HermesReflectionService(
            self.repo,
            FailingLLM(),
            weekly_report_builder=lambda: "weekly report",
            memory_dir=self.memory_dir,
        )

        with self.assertRaises(RuntimeError):
            service.generate_reflection(days=7, notify_lark=False)

        run = self.conn.execute(
            "SELECT * FROM run_logs WHERE run_type = 'hermes_reflection' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        reflection_count = self.conn.execute("SELECT COUNT(*) AS count FROM reflections").fetchone()["count"]
        self.assertEqual(run["status"], "failed")
        self.assertIn("model unavailable", run["error_message"])
        self.assertEqual(reflection_count, 0)

    def _add_recommendation(self, theme):
        run_id = self.repo.create_run("test")
        return self.repo.add_recommendation(
            run_id,
            RecommendationDraft(
                title="Test Book",
                author="A",
                source_url="",
                slot_type="profile_fit",
                theme=theme,
                recommendation_reason="推荐理由",
                profile_mapping="画像映射",
                system_hypothesis=f"测试用户是否关注 {theme}",
                profile_dimensions=["knowledge_gap", "system_reliability"],
                expected_benefit="收益",
                risk="风险",
                reading_suggestion="建议",
                metadata={},
            ),
            __import__("datetime").date.today(),
        )


def reflection_response():
    return {
        "period_summary": "本周画像摘要：用户继续偏好工程实践。",
        "accurate_observations": ["稳定关注系统可靠性"],
        "long_term_interest_changes": ["工程系统化判断增强"],
        "short_term_focus_changes": ["关注 SQLite 与自动化闭环"],
        "knowledge_gaps": ["长期记忆合并策略"],
        "reading_preferences": ["偏好可执行材料"],
        "aversion_patterns": ["不喜欢营销感强的材料"],
        "action_stage": "正在把 MVP 加固为可运营系统",
        "system_misunderstandings": ["可能高估了对泛 AI 商业书的兴趣"],
        "next_week_strategy": ["下周减少营销类内容"],
        "reflection_questions": ["下周更想补工程还是产品？", "哪些推荐过于泛化？", "是否需要更深代码案例？"],
        "user_md_patch": "- 用户偏好工程实践与可落地方案。",
        "memory_md_patch": "- 下周减少营销类内容，增加一手资料和工程案例。",
    }


if __name__ == "__main__":
    unittest.main()
