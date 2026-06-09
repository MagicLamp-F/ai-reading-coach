import json
import subprocess
import unittest

from app.daily_agent_adapter import (
    HermesDailyRecommendationAdapter,
    build_daily_recommendation_agent,
    build_effective_profile_summary,
    daily_recommendation_runtime_capabilities,
    normalize_agentic_shadow,
    normalize_recommendation_plan,
    normalize_theme_intents,
)


class DailyAgentAdapterTests(unittest.TestCase):
    def test_build_daily_recommendation_agent_returns_none_for_custom(self):
        self.assertIsNone(build_daily_recommendation_agent("custom", "cmd", 1))

    def test_hermes_adapter_reports_reflect_json_runtime_capabilities(self):
        adapter = HermesDailyRecommendationAdapter("/tmp/hermes-route", timeout_seconds=12)

        capabilities = daily_recommendation_runtime_capabilities(adapter)

        self.assertEqual(capabilities["schema_version"], "daily_agent_runtime_capabilities_v1")
        self.assertEqual(capabilities["provider"], "hermes-agent")
        self.assertEqual(capabilities["runtime"], "reflect-json")
        self.assertFalse(capabilities["supports_native_thread"])
        self.assertFalse(capabilities["supports_delegation"])
        self.assertFalse(capabilities["supports_memory"])
        self.assertFalse(capabilities["supports_file"])
        self.assertFalse(capabilities["supports_terminal"])
        self.assertFalse(capabilities["supports_web"])
        self.assertFalse(capabilities["supports_session_search"])
        self.assertFalse(capabilities["side_effects_allowed"])

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

    def test_hermes_adapter_plans_recommendations_with_route_payload(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            calls.append(json.loads(input))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "slots": [
                            {
                                "slot_type": "profile_fit",
                                "theme": "经典文学",
                                "search_queries": ["经典文学 高口碑 长篇小说 书籍"],
                                "candidate_criteria": ["必须是书"],
                                "risk_controls": ["避开已读"],
                                "reason": "文学偏好",
                            },
                            {
                                "slot_type": "profile_fit",
                                "theme": "科幻经典",
                                "search_queries": ["科幻经典 文明 技术伦理 书籍"],
                                "candidate_criteria": ["有明确作者"],
                                "risk_controls": ["避免文章"],
                                "reason": "科幻偏好",
                            },
                            {
                                "slot_type": "exploration",
                                "theme": "历史叙事探索",
                                "search_queries": ["历史叙事 非虚构 高口碑 书籍"],
                                "candidate_criteria": ["探索但不偏离阅读偏好"],
                                "risk_controls": ["避免营销"],
                                "reason": "探索新方向",
                            },
                        ],
                        "global_risk_controls": ["hard exclusions are binding"],
                        "plan_summary": "summary",
                        "confidence": 0.7,
                    },
                    ensure_ascii=False,
                ),
                stderr="",
            )

        adapter = HermesDailyRecommendationAdapter("/tmp/hermes-route", timeout_seconds=12, runner=runner)

        plan = adapter.plan_recommendations("profile", "history")

        self.assertEqual(plan["schema_version"], "recommendation_plan_v1")
        self.assertEqual(plan["slots"][0]["theme"], "经典文学")
        self.assertEqual(calls[0]["route"], "reading.recommend.plan_v1")
        self.assertEqual(calls[0]["output_schema"], "recommendation_plan_v1")
        self.assertEqual(calls[0]["context"]["recommendation_history_context"], "history")
        self.assertTrue(calls[0]["constraints"]["do_not_modify_sqlite"])
        self.assertTrue(calls[0]["constraints"]["do_not_modify_files"])
        self.assertTrue(calls[0]["constraints"]["do_not_send_messages"])
        self.assertIn("只读 planning route", calls[0]["system_prompt"])
        self.assertIn("search_queries", calls[0]["user_prompt"])

    def test_recommendation_plan_normalization_bounds_slots(self):
        plan = normalize_recommendation_plan(
            {
                "slots": [
                    {
                        "slot": "fit",
                        "theme": "A" * 200,
                        "queries": ["q"],
                        "criteria": ["c"],
                        "risk_controls": ["r"],
                    }
                ],
                "confidence": 2,
            }
        )

        self.assertEqual(plan["schema_version"], "recommendation_plan_v1")
        self.assertEqual(plan["slots"][0]["slot_type"], "profile_fit")
        self.assertEqual(len(plan["slots"][0]["theme"]), 120)
        self.assertEqual(plan["slots"][0]["search_queries"], ["q"])
        self.assertEqual(plan["confidence"], 1.0)

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
        self.assertEqual(generate_session["context_type"], "arc_explicit_payload_context")
        self.assertNotIn("previous_turns", generate_session)
        self.assertEqual(generate_session["explicit_payload_context_turns"][0]["route"], "reading.recommend.intent")
        self.assertEqual(generate_session["explicit_payload_context_turns"][0]["response_summary"]["themes"], themes)
        self.assertEqual(calls[1]["context"]["theme_intents"][0]["slot"], "profile_fit")
        self.assertEqual(calls[1]["context"]["theme_intents"][2]["slot"], "exploration")
        self.assertEqual(calls[1]["context"]["theme_intents"][2]["reason"], "验证新方向")

    def test_hermes_adapter_reviews_recommendations_with_shadow_route_payload(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            calls.append(json.loads(input))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "verdict": "accept",
                        "candidate_reviews": [
                            {
                                "title": "Reviewed Book",
                                "author": "Hermes",
                                "status": "keep",
                                "reasons": ["fits profile"],
                                "profile_fit_score": 0.9,
                                "fatigue_risk": "low",
                                "start_path_quality": "good",
                                "resource_type_risk": "none",
                            }
                        ],
                        "global_warnings": [],
                        "revision_instructions": [],
                        "confidence": 0.8,
                    },
                    ensure_ascii=False,
                ),
                stderr="",
            )

        adapter = HermesDailyRecommendationAdapter("/tmp/hermes-route", timeout_seconds=12, runner=runner)

        review = adapter.review_recommendations(
            profile_context="profile",
            recommendation_history_context="history",
            themes=["经典文学", "科幻", "探索"],
            generated_candidates=[{"title": "Reviewed Book", "author": "Hermes"}],
            selected_recommendations=[{"title": "Reviewed Book", "author": "Hermes"}],
        )

        self.assertEqual(review["verdict"], "accept")
        self.assertEqual(calls[0]["route"], "reading.recommend.review_v1")
        self.assertEqual(calls[0]["output_schema"], "recommendation_review_v1")
        self.assertEqual(calls[0]["context"]["recommendation_history_context"], "history")
        self.assertEqual(calls[0]["context"]["generated_candidates"][0]["title"], "Reviewed Book")
        self.assertTrue(calls[0]["constraints"]["do_not_modify_sqlite"])
        self.assertTrue(calls[0]["constraints"]["do_not_send_messages"])
        self.assertIn("shadow review", calls[0]["user_prompt"])

    def test_hermes_adapter_runs_agentic_shadow_with_route_payload(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            calls.append(json.loads(input))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "subagents_used": 2,
                        "roles": ["profile_history_reviewer", "source_quality_reviewer"],
                        "trace_mode": "simulated_trace",
                        "baseline_assessment": {
                            "profile_fit": 0.8,
                            "novelty": 0.6,
                            "start_path_quality": 0.7,
                            "source_validity": 0.9,
                            "risks": [],
                        },
                        "shadow_recommendations": [
                            {
                                "title": "Shadow Book",
                                "author": "Hermes",
                                "slot_type": "profile_fit",
                                "theme": "经典文学",
                                "reason": "better fit",
                                "source_url": "https://example.test/shadow",
                                "replace_baseline_title": "Baseline Book",
                            }
                        ],
                        "comparison": {
                            "baseline_strengths": ["safe"],
                            "shadow_strengths": ["novel"],
                            "tradeoffs": ["needs evidence"],
                            "recommended_action": "observe_only",
                        },
                        "warnings": [],
                        "confidence": 0.65,
                    },
                    ensure_ascii=False,
                ),
                stderr="",
            )

        adapter = HermesDailyRecommendationAdapter("/tmp/hermes-route", timeout_seconds=12, runner=runner)

        shadow = adapter.agentic_shadow_recommendations(
            profile_context="profile",
            recommendation_history_context="history",
            themes=["经典文学", "科幻", "探索"],
            recommendation_plan={"slots": [{"theme": "经典文学"}]},
            generated_candidates=[{"title": "Candidate Book", "author": "Hermes"}],
            selected_recommendations=[{"title": "Baseline Book", "author": "Hermes"}],
            shadow_config={"max_subagents": 2, "side_effects_allowed": False},
        )

        self.assertEqual(shadow["schema_version"], "agentic_shadow_v1")
        self.assertEqual(shadow["subagents_used"], 2)
        self.assertEqual(calls[0]["route"], "reading.recommend.agentic_shadow_v1")
        self.assertEqual(calls[0]["output_schema"], "agentic_shadow_v1")
        self.assertEqual(calls[0]["context"]["recommendation_history_context"], "history")
        self.assertEqual(calls[0]["context"]["shadow_config"]["max_subagents"], 2)
        self.assertTrue(calls[0]["constraints"]["do_not_modify_sqlite"])
        self.assertTrue(calls[0]["constraints"]["do_not_modify_files"])
        self.assertTrue(calls[0]["constraints"]["do_not_send_messages"])
        self.assertIn("只读 shadow route", calls[0]["system_prompt"])
        self.assertIn("agentic shadow", calls[0]["user_prompt"])

    def test_agentic_shadow_normalization_clamps_metadata(self):
        shadow = normalize_agentic_shadow(
            {
                "subagents_used": 99,
                "roles": ["r" * 200],
                "trace_mode": "unexpected",
                "warnings": ["w"],
                "confidence": 2,
            }
        )

        self.assertEqual(shadow["schema_version"], "agentic_shadow_v1")
        self.assertEqual(shadow["subagents_used"], 8)
        self.assertEqual(len(shadow["roles"][0]), 120)
        self.assertEqual(shadow["trace_mode"], "simulated_trace")
        self.assertEqual(shadow["confidence"], 1.0)


if __name__ == "__main__":
    unittest.main()
