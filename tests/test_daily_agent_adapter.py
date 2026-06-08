import json
import subprocess
import unittest

from app.daily_agent_adapter import (
    HermesDailyRecommendationAdapter,
    build_daily_recommendation_agent,
    build_effective_profile_summary,
    normalize_theme_intents,
)


class DailyAgentAdapterTests(unittest.TestCase):
    def test_build_daily_recommendation_agent_returns_none_for_custom(self):
        self.assertIsNone(build_daily_recommendation_agent("custom", "cmd", 1))

    def test_hermes_adapter_generates_themes_with_route_payload(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            calls.append(json.loads(input))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "themes": [
                            {"theme": "A", "slot": "profile_fit", "reason": "stable"},
                            {"theme": "B", "slot": "profile_fit", "reason": "stable"},
                            {"theme": "C", "slot": "exploration", "reason": "test"},
                        ]
                    }
                ),
                stderr="",
            )

        adapter = HermesDailyRecommendationAdapter("/tmp/hermes-route", timeout_seconds=12, runner=runner)

        themes = adapter.generate_themes("profile", "history")

        self.assertEqual(themes, ["A", "B", "C"])
        self.assertEqual(calls[0]["route"], "reading.recommend.intent")
        self.assertEqual(calls[0]["output_schema"], "themes_v2")
        self.assertEqual(calls[0]["context"]["recommendation_history_context"], "history")
        self.assertEqual(calls[0]["output_contract"]["themes"][0]["slot"], "profile_fit|exploration")
        self.assertTrue(calls[0]["constraints"]["do_not_send_messages"])
        self.assertTrue(calls[0]["constraints"]["do_not_modify_files"])
        self.assertTrue(calls[0]["constraints"]["do_not_modify_memories"])
        self.assertIn("effective_profile_summary", calls[0]["context"])
        self.assertIn("The first 2 themes must be profile_fit", calls[0]["user_prompt"])
        self.assertIn("classic science fiction", calls[0]["user_prompt"])
        self.assertIn("concrete enough to guide downstream book selection", calls[0]["user_prompt"])
        self.assertIn('"slot":"profile_fit"', calls[0]["user_prompt"])

    def test_theme_intent_normalization_accepts_legacy_strings(self):
        intents = normalize_theme_intents(["文学经典", "科幻经典", "社会派探索"])

        self.assertEqual([intent.theme for intent in intents], ["文学经典", "科幻经典", "社会派探索"])
        self.assertEqual([intent.slot for intent in intents], ["profile_fit", "profile_fit", "exploration"])

    def test_effective_profile_summary_keeps_stable_book_signals(self):
        profile_context = "\n".join(
            [
                "Priority 1: Hermes native USER memory reading profile:",
                "Hermes native USER.md [arc-reading-profile]:",
                "[arc-reading-profile] User reading profile: 偏好经典名著、高口碑中文文学、科幻经典。",
                "Priority 4: ARC applied reflection memory:",
                "- 推荐书籍本身，不要技术文章",
                "- AI Agent 商业化需要降频",
                "Priority 5: Single-run weak signals:",
                "- 本次搜索结果只作待验证假设",
            ]
        )

        summary = build_effective_profile_summary(profile_context)

        self.assertIn("EffectiveProfileSummary", summary)
        self.assertIn("偏好经典名著、高口碑中文文学、科幻经典", summary)
        self.assertIn("AI Agent 商业化需要降频", summary)
        self.assertIn("Favor concrete book themes", summary)

    def test_hermes_adapter_generates_recommendations_with_route_payload(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            calls.append(json.loads(input))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "books": [
                            {
                                "title": "Hermes Book",
                                "author": "Hermes",
                                "source_url": "",
                                "slot_type": "profile_fit",
                                "theme": "AI",
                                "system_hypothesis": "h",
                                "profile_dimensions": ["d"],
                                "recommendation_reason": "r",
                                "profile_mapping": "m",
                                "expected_benefit": "b",
                                "risk": "risk",
                                "reading_suggestion": "s",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                stderr="",
            )

        adapter = HermesDailyRecommendationAdapter("/tmp/hermes-route", timeout_seconds=12, runner=runner)

        books = adapter.generate_recommendations("profile", ["AI"], [], recommendation_history_context="history")

        self.assertEqual(books[0]["title"], "Hermes Book")
        self.assertEqual(calls[0]["route"], "reading.recommend.generate")
        self.assertEqual(calls[0]["output_schema"], "recommendations_v1")
        self.assertEqual(calls[0]["context"]["recommendation_history_context"], "history")

    def test_hermes_adapter_passes_bounded_local_session_between_route_calls(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            payload = json.loads(input)
            calls.append(payload)
            if payload["route"] == "reading.recommend.intent":
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout=json.dumps(
                        {
                            "themes": [
                                {"theme": "经典文学", "slot": "profile_fit", "reason": "文学偏好"},
                                {"theme": "科幻", "slot": "profile_fit", "reason": "科幻偏好"},
                                {"theme": "探索", "slot": "exploration", "reason": "验证新方向"},
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "books": [
                            {
                                "title": "Session Book",
                                "author": "Hermes",
                                "source_url": "",
                                "slot_type": "profile_fit",
                                "theme": "经典文学",
                                "system_hypothesis": "h",
                                "profile_dimensions": ["d"],
                                "recommendation_reason": "r",
                                "profile_mapping": "m",
                                "expected_benefit": "b",
                                "risk": "risk",
                                "reading_suggestion": "s",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                stderr="",
            )

        adapter = HermesDailyRecommendationAdapter("/tmp/hermes-route", timeout_seconds=12, runner=runner)

        adapter.start_local_session(run_id=42, purpose="run_daily")
        themes = adapter.generate_themes("profile", "history")
        adapter.generate_recommendations("profile", themes, [], recommendation_history_context="history")
        adapter.end_local_session()

        intent_session = calls[0]["context"]["local_session"]
        generate_session = calls[1]["context"]["local_session"]
        self.assertTrue(intent_session["enabled"])
        self.assertEqual(intent_session["session_id"], "arc-run_daily-42")
        self.assertEqual(intent_session["hermes_internal_thread"], "not_supported_by_current_reflect_json_wrapper")
        self.assertEqual(generate_session["previous_turns"][0]["route"], "reading.recommend.intent")
        self.assertEqual(generate_session["previous_turns"][0]["response_summary"]["themes"], themes)
        self.assertEqual(calls[1]["context"]["theme_intents"][0]["slot"], "profile_fit")
        self.assertEqual(calls[1]["context"]["theme_intents"][2]["slot"], "exploration")
        self.assertEqual(calls[1]["context"]["theme_intents"][2]["reason"], "验证新方向")


if __name__ == "__main__":
    unittest.main()
