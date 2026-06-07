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


if __name__ == "__main__":
    unittest.main()
