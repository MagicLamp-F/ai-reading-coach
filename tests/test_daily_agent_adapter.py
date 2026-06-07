import json
import subprocess
import unittest

from app.daily_agent_adapter import HermesDailyRecommendationAdapter, build_daily_recommendation_agent


class DailyAgentAdapterTests(unittest.TestCase):
    def test_build_daily_recommendation_agent_returns_none_for_custom(self):
        self.assertIsNone(build_daily_recommendation_agent("custom", "cmd", 1))

    def test_hermes_adapter_generates_themes_with_route_payload(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            calls.append(json.loads(input))
            return subprocess.CompletedProcess(argv, 0, stdout='{"themes":["A","B","C"]}', stderr="")

        adapter = HermesDailyRecommendationAdapter("/tmp/hermes-route", timeout_seconds=12, runner=runner)

        themes = adapter.generate_themes("profile", "history")

        self.assertEqual(themes, ["A", "B", "C"])
        self.assertEqual(calls[0]["route"], "reading.recommend.intent")
        self.assertEqual(calls[0]["output_schema"], "themes_v1")
        self.assertEqual(calls[0]["context"]["recommendation_history_context"], "history")
        self.assertTrue(calls[0]["constraints"]["do_not_send_messages"])

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
                return subprocess.CompletedProcess(argv, 0, stdout='{"themes":["经典文学","科幻","探索"]}', stderr="")
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


if __name__ == "__main__":
    unittest.main()
