import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.db import connect, init_db
from app.reading_pack import FastReadPackService, HermesReadingPackAdapter, ReadingPackError, build_reading_pack_agent
from app.repository import BookSourceDraft, RecommendationDraft, Repository


class PackLLM:
    api_key = "test-key"
    model = "test-model"

    def complete_json(self, system_prompt, user_prompt):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return {
            "pack_title": "测试书 快速读完包",
            "copyright_note": "不复刻全书。",
            "source_note": "基于推荐记录和公开信息。",
            "why_recommended": "它匹配当前工程化诉求。",
            "one_sentence_thesis": "系统化能力来自可靠的反馈闭环。",
            "problem_statement": "作者试图解决复杂系统不可维护的问题。",
            "core_argument_chain": ["先识别瓶颈", "再设计反馈", "最后形成可维护机制"],
            "chapter_map": ["第一部分：问题", "第二部分：方法", "第三部分：应用"],
            "core_concepts": ["反馈闭环", "系统边界"],
            "key_examples": ["用运行日志定位问题"],
            "reading_routes": {
                "ten_min": "读核心论点。",
                "thirty_min": "读章节地图和案例。",
                "two_hour": "按问题精读。",
            },
            "skip_or_defer": ["先跳过不相关案例"],
            "limitations": ["公开来源不足时需要人工校验"],
            "user_application": "用于改进 ai-reading-coach 的业务复盘页面。",
            "self_test_questions": ["我能解释这本书的主张吗？"],
        }


class FailingPackLLM:
    api_key = "test-key"
    model = "test-model"

    def complete_json(self, system_prompt, user_prompt):
        raise RuntimeError("model unavailable")


class ReadingPackTests(unittest.TestCase):
    def test_build_reading_pack_agent_returns_hermes_adapter(self):
        adapter = build_reading_pack_agent("hermes-agent", "/tmp/hermes-route", 12)

        self.assertIsInstance(adapter, HermesReadingPackAdapter)

    def test_hermes_reading_pack_adapter_sends_fast_read_route_payload(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            calls.append(json.loads(input))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "pack_title": "Hermes Pack",
                        "one_sentence_thesis": "Hermes thesis",
                        "core_argument_chain": ["A", "B"],
                        "chapter_map": ["Part 1"],
                        "core_concepts": ["Concept"],
                        "key_examples": ["Example"],
                        "reading_routes": {"ten_min": "Ten", "thirty_min": "Thirty", "two_hour": "Two"},
                    }
                ),
                stderr="",
            )

        adapter = HermesReadingPackAdapter("/tmp/hermes-route", timeout_seconds=12, runner=runner)

        response = adapter.generate_pack("context")

        self.assertEqual(response["pack_title"], "Hermes Pack")
        self.assertEqual(calls[0]["route"], "reading.deep_read_pack")
        self.assertEqual(calls[0]["output_schema"], "deep_read_pack_v2")
        self.assertIn("压缩穿过全书", calls[0]["user_prompt"])

    def test_generate_reading_pack_writes_artifact_and_database_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = _repo_with_recommendation(tmp_path)
            source_id = repo.upsert_book_source(
                BookSourceDraft(
                    book_id=1,
                    source_type="official_page",
                    url="https://example.com/book",
                    title="测试书 official page",
                    text_excerpt="这本书的公开页面说明它讨论反馈闭环、系统边界和维护机制。",
                    metadata={"source": "test"},
                )
            )
            llm = PackLLM()
            memory_dir = tmp_path / "memory"
            memory_dir.mkdir()
            (memory_dir / "HERMES_NATIVE_PROFILE.md").write_text(
                "# HERMES_NATIVE_PROFILE\n\nReading Preferences: 深读业务系统和经典文本",
                encoding="utf-8",
            )
            service = FastReadPackService(repo, llm, memory_dir=memory_dir, library_dir=tmp_path / "library")

            result = service.generate_for_recommendation(1)

            pack = repo.get_reading_pack(result.reading_pack_id)
            self.assertEqual(result.status, "generated")
            self.assertIsNotNone(pack)
            self.assertEqual(pack["status"], "generated")
            self.assertEqual(pack["route"], "reading.deep_read_pack")
            self.assertTrue(Path(pack["artifact_path"]).exists())
            markdown = Path(pack["artifact_path"]).read_text(encoding="utf-8")
            self.assertIn("## Argument Walkthrough", markdown)
            self.assertIn("## Source Quality And References", markdown)
            self.assertIn("系统化能力来自可靠的反馈闭环", markdown)
            content = json.loads(pack["content_json"])
            self.assertEqual(content["schema_version"], "deep_read_pack_v2")
            self.assertEqual(content["route"], "reading.deep_read_pack")
            self.assertEqual(content["depth_profile"], "deep_v2")
            self.assertEqual(content["expanded_argument"][0], "先识别瓶颈")
            self.assertEqual(content["source_refs"][0]["id"], str(source_id))
            self.assertEqual(content["source_quality"]["status"], "source_limited")
            self.assertEqual(result.preview.source_status, "source_limited")
            self.assertEqual(result.preview.source_count, 1)
            self.assertEqual(repo.reading_pack_sources(result.reading_pack_id)[0]["id"], source_id)
            self.assertIn("User profile context", llm.user_prompt)
            self.assertIn("Priority 1: Hermes native USER memory reading profile", llm.user_prompt)
            self.assertIn("深读业务系统和经典文本", llm.user_prompt)
            self.assertIn("Book source excerpts", llm.user_prompt)
            self.assertIn("反馈闭环、系统边界和维护机制", llm.user_prompt)

    def test_generate_reading_pack_falls_back_when_model_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = _repo_with_recommendation(tmp_path)
            service = FastReadPackService(repo, FailingPackLLM(), memory_dir=tmp_path / "memory", library_dir=tmp_path / "library")

            result = service.generate_for_recommendation(1)

            pack = repo.get_reading_pack(result.reading_pack_id)
            self.assertEqual(result.status, "fallback")
            self.assertIsNotNone(pack)
            self.assertEqual(pack["status"], "fallback")
            self.assertIn("model unavailable", pack["error_message"])
            self.assertTrue(Path(pack["artifact_path"]).exists())

    def test_generate_reading_pack_requires_existing_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            init_db(conn)
            repo = Repository(conn)
            service = FastReadPackService(repo, PackLLM(), library_dir=Path(tmp) / "library")

            with self.assertRaises(ReadingPackError):
                service.generate_for_recommendation(999)


def _repo_with_recommendation(tmp_path: Path) -> Repository:
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    repo = Repository(conn)
    run_id = repo.create_run("test")
    repo.add_recommendation(
        run_id,
        RecommendationDraft(
            title="测试书",
            author="作者",
            source_url="https://example.com/book",
            slot_type="profile_fit",
            theme="工程化复盘",
            recommendation_reason="它能帮助你把阅读系统做成可维护业务。",
            profile_mapping="匹配长期目标：AI 读书私教和业务页面复盘。",
            system_hypothesis="如果用户能快速理解书的结构，就更容易决定是否深读。",
            profile_dimensions=["reading_preference", "software_engineering_practice"],
            expected_benefit="补齐快速理解一本书的内容层。",
            risk="可能过于概括，需要后续补来源。",
            reading_suggestion="先读结构和案例，再决定是否深读。",
            metadata={"source": "test"},
        ),
        date(2026, 5, 31),
    )
    return repo


if __name__ == "__main__":
    unittest.main()
