from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from app.feedback import FEEDBACK_LABELS, FEEDBACK_REASON_LABELS, FEEDBACK_TYPES, build_feedback_url, build_reading_pack_url
from app.daily_agent_adapter import (
    DailyRecommendationAgentAdapter,
    THEME_GENERATION_RULES,
    daily_recommendation_runtime_capabilities,
)
from app.lark import LarkFeedbackLink, LarkRobotClient
from app.llm import OpenAIChatClient
from app.memory import DEFAULT_LONG_TERM_MEMORY_MAX_CHARS, HermesNativeProfileProvider
from app.memory import build_daily_profile_context as build_prioritized_daily_profile_context
from app.memory import build_native_profile_seed_context
from app.memory import load_long_term_memory_context
from app.profile import PROFILE_CATEGORIES, build_profile_context, process_feedback
from app.profile_ingest import FeedbackProfileIngestor
from app.recommendation_agentic_shadow import RecommendationAgenticShadowService
from app.recommendation_candidate_research import RecommendationCandidateResearchService
from app.recommendation_explainability import RecommendationCandidateExplainabilityService
from app.recommendation_fact_check import RecommendationFactCheckService
from app.recommendation_gating import RecommendationGatingService
from app.recommendation_plan import RecommendationPlanService
from app.recommendation_review import RecommendationReviewShadowService
from app.reading_pack import FastReadPackService, HermesReadingPackAdapter, ReadingPackPreview, build_reading_pack_preview
from app.repository import DeliveryOutboxDraft, RecommendationCandidateDraft, RecommendationDraft, Repository
from app.search import SearchResult, TavilySearch
from app.source_collector import (
    BookSourceCollector,
    is_article_like_book_source_url,
    is_preferred_book_landing_url,
    source_quality_from_sources,
)
from app.telegram import feedback_markup, format_recommendation_message, TelegramClient

logger = logging.getLogger(__name__)


DEFAULT_THEMES = ["AI Agent 商业化", "个人知识管理", "软件工程实践"]
MISUNDERSTANDING_REASON_CODES = {
    "wrong_timing",
    "topic_irrelevant",
    "topic_slightly_far",
    "reason_not_convincing",
    "need_more_practical",
    "too_theoretical",
    "too_marketing",
}
EMPTY_RECOMMENDATION_HISTORY_CONTEXT = "暂无推荐历史。"

FALLBACK_BOOKS = [
    {
        "title": "Designing Data-Intensive Applications",
        "author": "Martin Kleppmann",
        "theme": "软件工程实践",
        "source_url": "https://dataintensive.net/",
        "recommendation_reason": "适合用来补齐数据库、系统边界和可靠性方面的基础判断。",
        "profile_mapping": "知识缺口：数据库设计、成本控制、Agent 权限边界",
        "system_hypothesis": "如果用户正在把 MVP 推向可维护系统，那么系统设计和可靠性基础会比单点框架技巧更能提升决策质量。",
        "profile_dimensions": ["knowledge_gap", "software_engineering_practice", "system_reliability"],
        "expected_benefit": "帮助你把 MVP 从脚本推进到可维护系统。",
        "risk": "篇幅较长，不适合作为短时间速读材料。",
        "reading_suggestion": "先读数据模型、存储、分布式系统相关章节，不必从头到尾读完。",
    },
    {
        "title": "Building a Second Brain",
        "author": "Tiago Forte",
        "theme": "个人知识管理",
        "source_url": "https://www.buildingasecondbrain.com/book",
        "recommendation_reason": "和个人认知画像、阅读反馈闭环高度相关。",
        "profile_mapping": "长期兴趣：个人效率系统、长期记忆、阅读系统搭建",
        "system_hypothesis": "如果用户重视长期知识沉淀，那么结构化信息管理方法会增强阅读反馈闭环的持续收益。",
        "profile_dimensions": ["long_term_interest", "reading_preference", "personal_knowledge_management"],
        "expected_benefit": "提供一套可操作的信息沉淀框架。",
        "risk": "如果你更偏工程实现，部分内容可能显得方法论较多。",
        "reading_suggestion": "重点看 PARA、渐进式总结和项目化使用部分。",
    },
    {
        "title": "Competing in the Age of AI",
        "author": "Marco Iansiti, Karim R. Lakhani",
        "theme": "AI Agent 商业化",
        "source_url": "https://www.hbs.edu/faculty/Pages/item.aspx?num=57624",
        "recommendation_reason": "适合从商业系统角度理解 AI 产品如何形成运营优势。",
        "profile_mapping": "长期兴趣：AI Agent 商业化、SaaS 早期融资",
        "system_hypothesis": "如果用户关注 AI Agent 商业化，那么从组织和运营系统角度理解 AI 原生公司会补齐商业判断维度。",
        "profile_dimensions": ["long_term_interest", "business_strategy", "ai_agent_commercialization"],
        "expected_benefit": "帮助你把技术系统和商业模式连接起来。",
        "risk": "不是具体 Agent 工程教程。",
        "reading_suggestion": "先读平台运营、规模化和组织设计相关章节。",
    },
]


class ReadingCoachWorkflow:
    def __init__(
        self,
        repo: Repository,
        search: TavilySearch,
        llm: OpenAIChatClient,
        lark: LarkRobotClient,
        telegram: TelegramClient,
        channel: str,
        public_base_url: str,
        feedback_secret: str,
        max_search_calls: int,
        max_model_calls: int,
        daily_recommendation_count: int = 3,
        memory_dir: Path = Path("memory"),
        max_memory_chars: int = DEFAULT_LONG_TERM_MEMORY_MAX_CHARS,
        hermes_native_profile_provider: HermesNativeProfileProvider | None = None,
        reading_packs_enabled: bool = False,
        reading_pack_library_dir: Path = Path("library"),
        daily_recommendation_agent: DailyRecommendationAgentAdapter | None = None,
        reading_pack_agent: HermesReadingPackAdapter | None = None,
        source_collector: BookSourceCollector | None = None,
        source_aware_recommendations: bool = False,
        source_aware_strict_mode: bool = True,
        source_aware_candidate_count: int = 6,
        source_min_coverage_score: float = 0.5,
        source_aware_allow_limited_fill: bool = False,
        profile_ingestor: FeedbackProfileIngestor | None = None,
        recommend_review_shadow_enabled: bool | None = None,
        agentic_shadow_enabled: bool | None = None,
        review_gating_enabled: bool | None = None,
        candidate_research_enabled: bool | None = None,
        fact_check_enabled: bool | None = None,
    ):
        self.repo = repo
        self.search = search
        self.llm = llm
        self.lark = lark
        self.telegram = telegram
        self.channel = channel
        self.public_base_url = public_base_url
        self.feedback_secret = feedback_secret
        self.max_search_calls = max_search_calls
        self.max_model_calls = max_model_calls
        self.daily_recommendation_count = max(1, daily_recommendation_count)
        self.memory_dir = memory_dir
        self.max_memory_chars = max_memory_chars
        self.hermes_native_profile_provider = hermes_native_profile_provider or HermesNativeProfileProvider(
            snapshot_path=memory_dir / "HERMES_NATIVE_PROFILE.md"
        )
        self.reading_packs_enabled = reading_packs_enabled
        self.reading_pack_library_dir = reading_pack_library_dir
        self.daily_recommendation_agent = daily_recommendation_agent
        self.reading_pack_agent = reading_pack_agent
        self.source_collector = source_collector
        self.source_aware_recommendations = source_aware_recommendations
        self.source_aware_strict_mode = source_aware_strict_mode
        self.source_aware_candidate_count = source_aware_candidate_count
        self.source_min_coverage_score = source_min_coverage_score
        self.source_aware_allow_limited_fill = source_aware_allow_limited_fill
        self.profile_ingestor = profile_ingestor
        self.recommendation_review_shadow = RecommendationReviewShadowService(
            repo=repo,
            library_dir=reading_pack_library_dir,
            enabled=recommend_review_shadow_enabled,
        )
        self.recommendation_candidate_explainability = RecommendationCandidateExplainabilityService(
            repo=repo,
            library_dir=reading_pack_library_dir,
        )
        self.recommendation_candidate_research = RecommendationCandidateResearchService(
            repo=repo,
            library_dir=reading_pack_library_dir,
            enabled=candidate_research_enabled,
        )
        self.recommendation_fact_check = RecommendationFactCheckService(
            repo=repo,
            library_dir=reading_pack_library_dir,
            enabled=fact_check_enabled,
        )
        self.recommendation_plan = RecommendationPlanService(
            repo=repo,
            library_dir=reading_pack_library_dir,
        )
        self.recommendation_agentic_shadow = RecommendationAgenticShadowService(
            repo=repo,
            library_dir=reading_pack_library_dir,
            enabled=agentic_shadow_enabled,
        )
        self.recommendation_gating = RecommendationGatingService(
            repo=repo,
            library_dir=reading_pack_library_dir,
            enabled=review_gating_enabled,
        )

    def run_daily_recommendations(self) -> int:
        run_id = self.repo.create_run("daily_recommendation", {"channel": self.channel})
        self._record_daily_agent_runtime_capabilities(run_id)
        self._start_daily_agent_local_session(run_id)
        api_calls = 0
        try:
            processed_feedback = process_feedback(self.repo, profile_ingestor=self.profile_ingestor)
            structured_profile_context = build_profile_context(self.repo)
            long_term_memory_context = load_long_term_memory_context(self.memory_dir, self.max_memory_chars)
            profile_context = build_daily_profile_context(
                hermes_native_profile_context=self.hermes_native_profile_provider.load_context(
                    seed_context=build_native_profile_seed_context(
                        structured_profile_context=structured_profile_context,
                        long_term_memory_context=long_term_memory_context,
                    )
                ),
                structured_profile_context=structured_profile_context,
                long_term_memory_context=long_term_memory_context,
            )
            recommendation_history_context = build_recommendation_history_context(self.repo)
            recommendation_plan = self.recommendation_plan.run(
                run_id=run_id,
                agent=self.daily_recommendation_agent,
                profile_context=profile_context,
                recommendation_history_context=recommendation_history_context,
            )
            themes = _themes_from_recommendation_plan(recommendation_plan) or self._generate_themes(
                profile_context,
                recommendation_history_context,
            )
            if self.daily_recommendation_agent is None and self.llm.api_key:
                api_calls += 1
                self.repo.record_cost(run_id, "model", "generate_themes", 1, {"model": self.llm.model})

            search_results: list[SearchResult] = []
            for search_plan in _search_plans_for_themes(themes, recommendation_plan):
                if api_calls >= self.max_daily_api_calls:
                    break
                try:
                    results = self.search.search_books(
                        search_plan["query"],
                        max_results=4,
                    )
                except Exception:
                    logger.exception("Search failed for theme=%s; continuing without those results", search_plan["theme"])
                    continue
                if results:
                    search_results.extend(results)
                    api_calls += 1
                    self.repo.record_cost(
                        run_id,
                        "tavily",
                        "search_books",
                        1,
                        {
                            "theme": search_plan["theme"],
                            "query": search_plan["query"],
                            "source": search_plan["source"],
                        },
                    )

            self.recommendation_candidate_research.run(
                run_id=run_id,
                agent=self.daily_recommendation_agent,
                profile_context=profile_context,
                recommendation_history_context=recommendation_history_context,
                themes=themes,
                recommendation_plan=recommendation_plan,
                search_results=search_results,
            )

            recommendation_limit = (
                self.source_aware_candidate_count
                if self.source_aware_recommendations
                else self.daily_recommendation_count
            )
            drafts = self._generate_recommendations(
                profile_context,
                themes,
                search_results,
                recommendation_limit,
                recommendation_history_context,
            )
            raw_candidates = list(drafts)
            hard_exclusion_keys = _recommendation_hard_exclusion_keys(self.repo)
            drafts = self._filter_hard_excluded_drafts(run_id, drafts)
            generated_candidates = list(drafts)
            drafts = self._source_aware_rank_drafts(run_id, drafts)
            self.recommendation_candidate_explainability.write_artifact(
                run_id=run_id,
                raw_candidates=raw_candidates,
                selected_recommendations=drafts,
                hard_exclusion_keys=hard_exclusion_keys,
            )
            self.recommendation_fact_check.run(
                run_id=run_id,
                agent=self.daily_recommendation_agent,
                profile_context=profile_context,
                recommendation_history_context=recommendation_history_context,
                themes=themes,
                selected_recommendations=drafts,
            )
            self.recommendation_review_shadow.run(
                run_id=run_id,
                agent=self.daily_recommendation_agent,
                profile_context=profile_context,
                recommendation_history_context=recommendation_history_context,
                themes=themes,
                generated_candidates=generated_candidates,
                selected_recommendations=drafts,
            )
            self.recommendation_agentic_shadow.run(
                run_id=run_id,
                agent=self.daily_recommendation_agent,
                profile_context=profile_context,
                recommendation_history_context=recommendation_history_context,
                themes=themes,
                recommendation_plan=recommendation_plan,
                generated_candidates=generated_candidates,
                selected_recommendations=drafts,
            )
            self.recommendation_gating.run(
                run_id=run_id,
                selected_recommendations=drafts,
                target_count=self.daily_recommendation_count,
            )
            if self.daily_recommendation_agent is None and self.llm.api_key:
                api_calls += 1
                self.repo.record_cost(run_id, "model", "generate_recommendations", 1, {"model": self.llm.model})

            today = datetime.now().date()
            total = min(self.daily_recommendation_count, len(drafts))
            sent_drafts: list[RecommendationDraft] = []
            for index, draft in enumerate(drafts[: self.daily_recommendation_count], start=1):
                recommendation_id = self.repo.add_recommendation(run_id, draft, today)
                reading_pack_preview = self._generate_reading_pack_preview(run_id, recommendation_id)
                message_id = self._send_recommendation(index, total, recommendation_id, draft, reading_pack_preview)
                if message_id is None and self._recommendation_channel_enabled():
                    warning = f"recommendation delivery queued: recommendation_id={recommendation_id}"
                    if getattr(self.lark, "last_send_error", ""):
                        warning = f"{warning}: {self.lark.last_send_error}"
                    logger.warning(warning)
                    self.repo.record_run_warning(run_id, warning)
                    self.repo.enqueue_delivery(
                        DeliveryOutboxDraft(
                            channel=self.channel,
                            message_type="recommendation",
                            recommendation_id=recommendation_id,
                            metadata={"index": index, "total": total, "run_id": run_id},
                            last_error=getattr(self.lark, "last_send_error", "") or "send returned no message_id",
                            next_attempt_seconds=300,
                        )
                    )
                if message_id:
                    self.repo.set_recommendation_message_id(recommendation_id, message_id)
                sent_drafts.append(draft)

            self._send_profile_test_summary(run_id, sent_drafts)

            self.repo.finish_run(run_id, "success", api_calls=api_calls)
            logger.info("Daily recommendation run completed: processed_feedback=%s", processed_feedback)
            return run_id
        except Exception as exc:
            logger.exception("Daily recommendation run failed")
            self.repo.finish_run(run_id, "failed", error_message=str(exc), api_calls=api_calls)
            raise
        finally:
            self._end_daily_agent_local_session()

    @property
    def max_daily_api_calls(self) -> int:
        return self.max_search_calls + self.max_model_calls

    def _start_daily_agent_local_session(self, run_id: int) -> None:
        starter = getattr(self.daily_recommendation_agent, "start_local_session", None)
        if callable(starter):
            starter(run_id=run_id, purpose="run_daily")

    def _end_daily_agent_local_session(self) -> None:
        closer = getattr(self.daily_recommendation_agent, "end_local_session", None)
        if callable(closer):
            closer()

    def _record_daily_agent_runtime_capabilities(self, run_id: int) -> None:
        self.repo.merge_run_metadata(
            run_id,
            {
                "hermes_runtime_capabilities": daily_recommendation_runtime_capabilities(
                    self.daily_recommendation_agent
                )
            },
        )

    def build_weekly_report(self) -> str:
        return build_weekly_report_payload(self.repo)["report_text"]

    def send_weekly_report(self) -> None:
        run_id = self.repo.create_run("weekly_report", {"channel": self.channel})
        try:
            message_id = self._send_text(self.build_weekly_report())
            if message_id is None and self._text_channel_enabled():
                raise RuntimeError("weekly report send failed")
            self.repo.finish_run(run_id, "success")
        except Exception as exc:
            logger.exception("Weekly report failed")
            self.repo.finish_run(run_id, "failed", error_message=str(exc))
            raise

    def resend_pending_deliveries(self, limit: int = 20, max_attempts: int = 5) -> int:
        sent = 0
        for delivery in self.repo.pending_deliveries(limit):
            message_type = str(delivery["message_type"])
            if message_type != "recommendation":
                self.repo.mark_delivery_retry(
                    int(delivery["id"]),
                    f"unsupported message_type={message_type}",
                    next_attempt_seconds=3600,
                    max_attempts=max_attempts,
                )
                continue
            recommendation_id = delivery["recommendation_id"]
            if recommendation_id is None:
                self.repo.mark_delivery_retry(
                    int(delivery["id"]),
                    "missing recommendation_id",
                    next_attempt_seconds=3600,
                    max_attempts=max_attempts,
                )
                continue
            draft = self._draft_from_recommendation_id(int(recommendation_id))
            if draft is None:
                self.repo.mark_delivery_retry(
                    int(delivery["id"]),
                    f"recommendation not found: id={recommendation_id}",
                    next_attempt_seconds=3600,
                    max_attempts=max_attempts,
                )
                continue
            metadata = _json_loads(str(delivery["metadata_json"] or "{}"), {})
            index = int(metadata.get("index") or 1) if isinstance(metadata, dict) else 1
            total = int(metadata.get("total") or 1) if isinstance(metadata, dict) else 1
            reading_pack_preview = self._reading_pack_preview_for_recommendation(int(recommendation_id))
            message_id = self._send_recommendation(index, total, int(recommendation_id), draft, reading_pack_preview)
            if message_id is not None:
                if message_id:
                    self.repo.set_recommendation_message_id(int(recommendation_id), message_id)
                self.repo.mark_delivery_sent(int(delivery["id"]))
                sent += 1
                continue
            self.repo.mark_delivery_retry(
                int(delivery["id"]),
                getattr(self.lark, "last_send_error", "") or "send returned no message_id",
                next_attempt_seconds=900,
                max_attempts=max_attempts,
            )
        return sent

    def _send_recommendation(
        self,
        index: int,
        total: int,
        recommendation_id: int,
        draft: RecommendationDraft,
        reading_pack_preview: ReadingPackPreview | None = None,
    ) -> str | None:
        if self.channel == "telegram":
            message = format_recommendation_message(index, total, draft)
            return self.telegram.send_message(message, feedback_markup(recommendation_id))
        links = [
            LarkFeedbackLink(
                feedback_type=feedback_type,
                url=build_feedback_url(self.public_base_url, recommendation_id, feedback_type, self.feedback_secret),
            )
            for feedback_type in FEEDBACK_TYPES
        ]
        return self.lark.send_recommendation(index, total, draft, links, reading_pack_preview)

    def _draft_from_recommendation_id(self, recommendation_id: int) -> RecommendationDraft | None:
        row = self.repo.get_recommendation_detail(recommendation_id)
        if row is None:
            return None
        metadata = _json_loads(str(row["metadata_json"] or "{}"), {})
        return RecommendationDraft(
            title=str(row["title"]),
            author=str(row["author"]),
            source_url=str(row["source_url"]),
            slot_type=str(row["slot_type"]),
            theme=str(row["theme"]),
            recommendation_reason=str(row["recommendation_reason"]),
            profile_mapping=str(row["profile_mapping"]),
            system_hypothesis=str(row["system_hypothesis"]),
            profile_dimensions=_profile_dimensions(row["profile_dimensions"]),
            expected_benefit=str(row["expected_benefit"]),
            risk=str(row["risk"]),
            reading_suggestion=str(row["reading_suggestion"]),
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def _generate_reading_pack_preview(self, run_id: int, recommendation_id: int) -> ReadingPackPreview | None:
        if not self.reading_packs_enabled:
            return None
        try:
            result = FastReadPackService(
                repo=self.repo,
                llm=self.llm,
                memory_dir=self.memory_dir,
                library_dir=self.reading_pack_library_dir,
                max_memory_chars=self.max_memory_chars,
                hermes_native_profile_provider=self.hermes_native_profile_provider,
                agent=self.reading_pack_agent,
                source_collector=self.source_collector,
            ).generate_for_recommendation(recommendation_id)
            if result.status == "fallback" and result.error_message:
                warning = f"reading pack generation fallback: recommendation_id={recommendation_id}: {result.error_message}"
                logger.warning(warning)
                self.repo.record_run_warning(run_id, warning)
            return replace(
                result.preview,
                reading_pack_url=build_reading_pack_url(
                    self.public_base_url,
                    result.reading_pack_id,
                    self.feedback_secret,
                ),
            )
        except Exception as exc:
            warning = f"reading pack generation failed: recommendation_id={recommendation_id}: {exc}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

    def _reading_pack_preview_for_recommendation(self, recommendation_id: int) -> ReadingPackPreview | None:
        row = self.repo.latest_reading_pack_for_recommendation(recommendation_id)
        if row is None:
            return None
        content = _json_loads(str(row["content_json"] or "{}"), {})
        if not isinstance(content, dict):
            return None
        artifact_path = Path(str(row["artifact_path"] or ""))
        preview = build_reading_pack_preview(content, artifact_path, str(row["status"] or "generated"))
        return replace(
            preview,
            reading_pack_url=build_reading_pack_url(
                self.public_base_url,
                int(row["id"]),
                self.feedback_secret,
            ),
        )

    def _send_reading_pack_preview(
        self,
        run_id: int,
        recommendation_id: int,
        reading_pack_preview: ReadingPackPreview,
    ) -> None:
        if self.channel != "lark" or not self.lark.enabled():
            return
        try:
            message_id = self.lark.send_reading_pack_preview(reading_pack_preview)
        except Exception as exc:
            warning = f"reading pack preview lark send failed: recommendation_id={recommendation_id}: {exc}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return
        if message_id is None:
            warning = f"reading pack preview lark send failed: recommendation_id={recommendation_id}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)

    def _send_text(self, text: str) -> str | None:
        if self.channel == "telegram":
            return self.telegram.send_message(text)
        return self.lark.send_text(text)

    def _text_channel_enabled(self) -> bool:
        if self.channel == "telegram":
            return self.telegram.enabled()
        return self.lark.enabled()

    def _recommendation_channel_enabled(self) -> bool:
        if self.channel == "telegram":
            return self.telegram.enabled()
        return self.lark.enabled()

    def _send_profile_test_summary(self, run_id: int, drafts: list[RecommendationDraft]) -> None:
        if self.daily_recommendation_count < 3:
            return
        if self.channel != "lark" or not self.lark.enabled() or len(drafts) < 3:
            return
        try:
            message_id = self.lark.send_profile_test_summary(drafts[:3])
        except Exception as exc:
            warning = f"profile test summary lark send failed: {exc}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return
        if message_id is None:
            warning = "profile test summary lark send failed"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)

    def _generate_themes(self, profile_context: str, recommendation_history_context: str = "") -> list[str]:
        if self.daily_recommendation_agent is not None:
            return self.daily_recommendation_agent.generate_themes(profile_context, recommendation_history_context)
        try:
            response = self.llm.complete_json(
                "你是读书推荐系统的画像决策层。只输出 JSON。",
                (
                    "根据用户画像上下文和推荐历史生成今日推荐主题。要求 2 个贴合画像主题，1 个探索型主题。"
                    "如果画像显示用户偏好经典名著、文学、科幻或高口碑作品，主题必须明显覆盖这些方向，"
                    "避免重复最近高频主题，除非推荐历史显示用户明确正反馈。"
                    "不要只生成工程技术、商业或工具书主题。"
                    "主题必须能直接指导下游选书，不要输出过于抽象或无法映射到具体书籍的兴趣标签。"
                    "用户画像上下文按 Priority 1-5 分层；必须优先遵循 Hermes 原生 USER memory，"
                    "再参考明确反馈和 ARC reading profile；不要把单次弱信号写成长期偏好。"
                    f"\n\n{THEME_GENERATION_RULES}\n\n"
                    '输出格式：{"themes":["主题1","主题2","主题3"]}\n\n'
                    f"用户画像上下文：\n{profile_context}\n\n"
                    f"推荐历史上下文：\n{recommendation_history_context or EMPTY_RECOMMENDATION_HISTORY_CONTEXT}"
                ),
            )
        except Exception:
            logger.exception("Theme generation failed; using default themes")
            return DEFAULT_THEMES
        themes = response.get("themes") if isinstance(response, dict) else None
        if isinstance(themes, list) and themes:
            return [str(theme)[:80] for theme in themes[:3]]
        return DEFAULT_THEMES

    def _generate_recommendations(
        self,
        profile_context: str,
        themes: list[str],
        search_results: list[SearchResult],
        max_books: int = 3,
        recommendation_history_context: str = "",
    ) -> list[RecommendationDraft]:
        if self.daily_recommendation_agent is not None:
            books = self.daily_recommendation_agent.generate_recommendations(
                profile_context,
                themes,
                search_results,
                recommendation_history_context=recommendation_history_context,
                max_books=max_books,
            )
            drafts = [self._draft_from_dict(item) for item in books[:max_books] if isinstance(item, dict)]
            if not drafts:
                raise RuntimeError("Hermes daily recommendation generation returned no usable books")
            return drafts

        search_context = "\n".join(
            f"- {result.title}\n  {result.url}\n  {result.content[:300]}"
            for result in search_results[:12]
        )
        try:
            response = self.llm.complete_json(
                "你是读书私教系统的执行层。只输出 JSON，不要输出 Markdown。",
                (
                    "用户画像上下文按 Priority 1-5 分层；必须优先遵循 Hermes 原生 USER memory，"
                    "再参考明确反馈和 ARC reading profile；不要把单次弱信号写成长期偏好。"
                    f"基于用户画像上下文、推荐历史、今日主题和搜索结果，输出 {max_books} 本候选书。"
                    "优先推荐真正的书，尤其是经典名著、高口碑文学、严肃小说、科幻经典或长期被讨论的作品；"
                    "如果用户提到《一句顶一万句》《三体》这类偏好，应优先选择相近气质或同等口碑的书。"
                    "必须遵守推荐历史中的 Hard exclusions；避免 History fatigue 中的重复主题。"
                    "不要把云厂商文章、博客文章、课程页或普通技术文章当作书籍来源。"
                    "每本书必须包含 title, author, source_url, slot_type, theme, system_hypothesis, "
                    "profile_dimensions, recommendation_reason, profile_mapping, expected_benefit, risk, reading_suggestion。"
                    "建议额外包含 user_fit_score、candidate_reason 和 history_check。"
                    "system_hypothesis 说明这本书正在测试哪个用户假设；profile_dimensions 是画像维度字符串数组。"
                    "slot_type 只能是 profile_fit 或 exploration。"
                    '输出格式：{"books":[...]}。\n\n'
                    f"用户画像上下文：\n{profile_context}\n\n"
                    f"推荐历史上下文：\n{recommendation_history_context or EMPTY_RECOMMENDATION_HISTORY_CONTEXT}\n\n"
                    f"今日主题：{json.dumps(themes, ensure_ascii=False)}\n\n"
                    f"搜索结果：\n{search_context}"
                ),
            )
        except Exception:
            logger.exception("Recommendation generation failed; using fallback books")
            return [self._draft_from_dict(item) for item in FALLBACK_BOOKS]
        books = response.get("books") if isinstance(response, dict) else None
        if isinstance(books, list) and books:
            drafts = [self._draft_from_dict(item) for item in books[:max_books] if isinstance(item, dict)]
            if drafts:
                return drafts
        return [self._draft_from_dict(item) for item in FALLBACK_BOOKS]

    def _source_aware_rank_drafts(self, run_id: int, drafts: list[RecommendationDraft]) -> list[RecommendationDraft]:
        if not self.source_aware_recommendations or self.source_collector is None:
            return drafts[: self.daily_recommendation_count]
        ranked = []
        seen = set()
        for draft in drafts[: self.source_aware_candidate_count]:
            key = (draft.title.strip().lower(), draft.author.strip().lower())
            if key in seen:
                continue
            seen.add(key)
            book_id = self.repo.upsert_book(draft.title, draft.author, draft.source_url, draft.metadata)
            existing_sources = self.repo.book_sources_for_book(book_id, limit=10)
            if not existing_sources:
                self.source_collector.collect_for_book(book_id, draft.title, draft.author, draft.source_url)
            sources = self.repo.book_sources_for_book(book_id, limit=10)
            quality = source_quality_from_sources(sources)
            source_score = float(quality.get("score") or 0)
            user_fit_score = _float_score(draft.metadata.get("user_fit_score"), 0.65)
            preferred_source_url = _preferred_source_url(draft.source_url, sources)
            article_like_penalty = 0.25 if is_article_like_book_source_url(draft.source_url) and not preferred_source_url else 0.0
            landing_bonus = 0.08 if preferred_source_url or is_preferred_book_landing_url(draft.source_url) else 0.0
            final_score = round(max(0.0, (user_fit_score * 0.45) + (source_score * 0.55) + landing_bonus - article_like_penalty), 3)
            ranked_draft = draft
            if preferred_source_url and preferred_source_url != draft.source_url:
                ranked_draft = RecommendationDraft(
                    title=draft.title,
                    author=draft.author,
                    source_url=preferred_source_url,
                    slot_type=draft.slot_type,
                    theme=draft.theme,
                    recommendation_reason=draft.recommendation_reason,
                    profile_mapping=draft.profile_mapping,
                    system_hypothesis=draft.system_hypothesis,
                    profile_dimensions=draft.profile_dimensions,
                    expected_benefit=draft.expected_benefit,
                    risk=draft.risk,
                    reading_suggestion=draft.reading_suggestion,
                    metadata={**draft.metadata, "original_source_url": draft.source_url},
                )
            ranked.append(
                {
                    "draft": ranked_draft,
                    "book_id": book_id,
                    "quality": quality,
                    "user_fit_score": user_fit_score,
                    "final_score": final_score,
                    "preferred_source_url": preferred_source_url,
                }
            )

        ranked.sort(key=lambda item: item["final_score"], reverse=True)
        qualified = [item for item in ranked if float(item["quality"].get("score") or 0) >= self.source_min_coverage_score]
        selected = qualified[: self.daily_recommendation_count]
        if len(selected) < self.daily_recommendation_count and self.source_aware_allow_limited_fill:
            selected_ids = {id(item["draft"]) for item in selected}
            selected.extend(item for item in ranked if id(item["draft"]) not in selected_ids)  # type: ignore[arg-type]
            selected = selected[: self.daily_recommendation_count]

        selected_keys = {
            (item["draft"].title.strip().lower(), item["draft"].author.strip().lower())
            for item in selected
        }
        for item in ranked:
            draft = item["draft"]
            source_score = float(item["quality"].get("score") or 0)
            is_selected = (draft.title.strip().lower(), draft.author.strip().lower()) in selected_keys
            if is_selected:
                status = "selected"
                reject_reason = ""
            elif source_score < self.source_min_coverage_score:
                status = "rejected"
                reject_reason = "source_coverage_below_threshold"
            elif is_article_like_book_source_url(draft.source_url) and not item.get("preferred_source_url"):
                status = "rejected"
                reject_reason = "source_url_is_article_not_book_page"
            else:
                status = "rejected"
                reject_reason = "ranked_below_selected_candidates"
            self.repo.add_recommendation_candidate(
                RecommendationCandidateDraft(
                    run_id=run_id,
                    book_id=int(item["book_id"]),
                    title=draft.title,
                    author=draft.author,
                    source_url=draft.source_url,
                    source_provider="source_aware_v1",
                    candidate_reason=str(draft.metadata.get("candidate_reason", "")),
                    user_fit_score=float(item["user_fit_score"]),
                    source_coverage_score=source_score,
                    final_score=float(item["final_score"]),
                    source_status=str(item["quality"].get("status") or "source_missing"),
                    status=status,
                    reject_reason=reject_reason,
                    metadata={"source_quality": item["quality"], "draft_metadata": draft.metadata},
                )
            )

        target_count = min(self.daily_recommendation_count, len(ranked))
        if self.source_aware_strict_mode and len(selected) < target_count:
            warning = (
                f"source-aware recommendation selected fewer than {self.daily_recommendation_count} books: "
                f"selected={len(selected)} candidates={len(ranked)} threshold={self.source_min_coverage_score}"
            )
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
        return [item["draft"] for item in selected]

    def _filter_hard_excluded_drafts(self, run_id: int, drafts: list[RecommendationDraft]) -> list[RecommendationDraft]:
        hard_exclusions = _recommendation_hard_exclusion_keys(self.repo)
        if not hard_exclusions:
            return drafts
        kept = []
        rejected = []
        for draft in drafts:
            key = _book_key(draft.title, draft.author)
            if key in hard_exclusions:
                rejected.append(f"{draft.title} / {draft.author}")
            else:
                kept.append(draft)
        if rejected:
            warning = "hard-excluded recommendation candidates removed: " + "; ".join(rejected[:8])
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
        if drafts and not kept:
            raise RuntimeError("Hermes daily recommendation generation returned only hard-excluded books")
        return kept

    def _draft_from_dict(self, item: dict[str, Any]) -> RecommendationDraft:
        return RecommendationDraft(
            title=str(item.get("title", "Untitled"))[:200],
            author=str(item.get("author", ""))[:200],
            source_url=str(item.get("source_url", ""))[:500],
            slot_type=str(item.get("slot_type", "profile_fit"))[:40],
            theme=str(item.get("theme", DEFAULT_THEMES[0]))[:120],
            recommendation_reason=str(item.get("recommendation_reason", ""))[:800],
            profile_mapping=str(item.get("profile_mapping", ""))[:800],
            system_hypothesis=str(item.get("system_hypothesis", ""))[:1000],
            profile_dimensions=_profile_dimensions(item.get("profile_dimensions")),
            expected_benefit=str(item.get("expected_benefit", ""))[:800],
            risk=str(item.get("risk", ""))[:800],
            reading_suggestion=str(item.get("reading_suggestion", ""))[:800],
            metadata={
                "source": "llm_or_fallback",
                "user_fit_score": _float_score(item.get("user_fit_score"), 0.65),
                "candidate_reason": str(item.get("candidate_reason", item.get("recommendation_reason", "")))[:800],
            },
        )


def _themes_from_recommendation_plan(plan: dict[str, Any] | None) -> list[str]:
    if not isinstance(plan, dict):
        return []
    slots = plan.get("slots")
    if not isinstance(slots, list):
        return []
    themes = []
    for slot in slots[:3]:
        if not isinstance(slot, dict):
            continue
        theme = str(slot.get("theme") or "").strip()
        if theme:
            themes.append(theme[:80])
    return themes


def _search_plans_for_themes(themes: list[str], plan: dict[str, Any] | None) -> list[dict[str, str]]:
    plan_queries: dict[str, str] = {}
    if isinstance(plan, dict):
        slots = plan.get("slots")
        if isinstance(slots, list):
            for slot in slots:
                if not isinstance(slot, dict):
                    continue
                theme = str(slot.get("theme") or "").strip()
                queries = slot.get("search_queries")
                if not theme or not isinstance(queries, list):
                    continue
                query = next((str(item).strip() for item in queries if str(item).strip()), "")
                if query:
                    plan_queries[theme] = query[:240]

    search_plans = []
    for theme in themes[:3]:
        normalized_theme = str(theme).strip()[:80]
        if not normalized_theme:
            continue
        query = plan_queries.get(normalized_theme)
        if query:
            search_plans.append({"theme": normalized_theme, "query": query, "source": "recommendation_plan_v1"})
        else:
            search_plans.append(
                {
                    "theme": normalized_theme,
                    "query": f"{normalized_theme} 经典 名著 高口碑 文学 科幻 书籍 目录 书评",
                    "source": "default_theme",
                }
            )
    return search_plans


def build_weekly_report_payload(repo: Repository, days: int = 7) -> dict[str, Any]:
    days = max(1, min(int(days), 30))
    recommendation_count = repo.weekly_recommendation_count(days)
    feedback_type_counts = repo.weekly_feedback_type_counts(days)
    reason_code_counts = repo.weekly_reason_code_counts(days)
    dimension_counts = repo.weekly_feedback_dimension_counts(days)
    positive_theme_counts = repo.weekly_positive_theme_counts(days)
    misread_signal_counts = repo.weekly_misread_signal_counts(days)
    recent_profiles = repo.recent_profile_updates(days, limit=8)
    profile_items = repo.profile_items_for_report(days, limit=40)
    profile_misunderstanding_signals = repo.weekly_profile_misunderstanding_signals(days)
    recent_free_texts = repo.recent_feedback_free_texts(days, limit=3)
    enhanced_dimensions = repo.recent_profile_dimension_counts(days)
    feedback_processing = repo.weekly_feedback_processing_summary(days)
    hermes_profile_update_counts = repo.weekly_hermes_profile_update_status_counts(days)
    reflection_status_counts = repo.weekly_reflection_status_counts(days)

    feedback_total = sum(int(row["count"]) for row in feedback_type_counts)
    positive_total = sum(
        int(row["count"])
        for row in feedback_type_counts
        if row["feedback_type"] in {"like", "go_deeper", "already_read"}
    )
    hit_rate = round((positive_total / feedback_total) * 100, 1) if feedback_total else 0.0

    feedback_lines = [
        f"- {FEEDBACK_LABELS.get(row['feedback_type'], row['feedback_type'])} ({row['feedback_type']}): {row['count']}"
        for row in feedback_type_counts
    ] or ["- 暂无反馈"]
    reason_lines = [
        f"- {FEEDBACK_REASON_LABELS.get(row['reason_code'], row['reason_code'])} ({row['reason_code']}): {row['count']}"
        for row in reason_code_counts
    ] or ["- 暂无原因反馈"]
    dimension_lines = [
        f"- {_dimension_type_label(row['dimension_type'])} / {FEEDBACK_LABELS.get(row['feedback_type'], row['feedback_type'])}: {row['count']}"
        for row in dimension_counts
    ] or ["- 暂无可分布的反馈"]
    profile_sections = _profile_confidence_sections(profile_items, profile_misunderstanding_signals)
    enhanced_lines = [
        (
            f"- {PROFILE_CATEGORIES.get(row['category'], row['category'])}: "
            f"{row['item_count']} 条画像，证据 {int(row['evidence_count'] or 0)}，平均权重 {round(float(row['avg_weight'] or 0), 2)}"
        )
        for row in enhanced_dimensions
    ] or ["- 暂无明显增强的画像维度。"]
    misunderstanding_lines = _misunderstanding_lines(misread_signal_counts)
    free_text_lines = _free_text_summary_lines(recent_free_texts)
    next_direction_lines = _next_direction_lines(positive_theme_counts, recent_profiles, feedback_total)
    user_summary_lines = _user_weekly_summary_lines(
        recommendation_count,
        feedback_total,
        positive_total,
        hit_rate,
        profile_sections,
        misunderstanding_lines,
        next_direction_lines,
    )
    writeback_lines = _profile_writeback_lines(
        feedback_processing,
        hermes_profile_update_counts,
        reflection_status_counts,
    )
    report_text = (
        f"{days} 天画像复盘\n\n"
        "给你的结论\n"
        + "\n".join(user_summary_lines)
        + "\n\n画像写回状态\n"
        + "\n".join(writeback_lines)
        + "\n\n"
        "一、本周推荐概况\n"
        f"- 推荐总数：{recommendation_count}\n"
        f"- 反馈总数：{feedback_total}\n"
        f"- 正反馈数量：{positive_total}（like / go_deeper / already_read）\n"
        f"- 推荐命中率：{hit_rate}%\n\n"
        "二、本周反馈分布\n"
        + "\n".join(feedback_lines)
        + "\n\n原因分布\n"
        + "\n".join(reason_lines)
        + "\n\n探索/画像贴合/知识缺口反馈分布\n"
        + "\n".join(dimension_lines)
        + "\n\n三、画像置信度分层\n"
        + "稳定画像\n"
        + "\n".join(profile_sections["stable"])
        + "\n\n待验证画像\n"
        + "\n".join(profile_sections["pending"])
        + "\n\n新出现信号\n"
        + "\n".join(profile_sections["new"])
        + "\n\n可能误解\n"
        + "\n".join(profile_sections["misunderstood"])
        + "\n\n四、当前增强的画像维度\n"
        + "\n".join(enhanced_lines)
        + "\n\n五、系统可能的误解\n"
        + "\n".join(misunderstanding_lines)
        + "\n\n六、最近自由文本补充\n"
        + "\n".join(free_text_lines)
        + "\n\n七、下周建议探索方向\n"
        + "\n".join(next_direction_lines)
        + "\n\n八、需要你回答的 3 个反思问题\n"
        + "1. 本周哪一次推荐最贴近你当前真实问题？为什么？\n"
        + "2. 哪类推荐看起来合理但实际不想读？主要原因是主题、难度、时机还是书本身？\n"
        + "3. 下周你更希望系统加深一个已有方向，还是探索一个新方向？"
    )
    return {
        "days": days,
        "metrics": {
            "recommendation_count": recommendation_count,
            "feedback_total": feedback_total,
            "positive_total": positive_total,
            "hit_rate": hit_rate,
        },
        "user_summary": user_summary_lines,
        "writeback_status": writeback_lines,
        "profile_sections": profile_sections,
        "enhanced_dimensions": enhanced_lines,
        "misunderstandings": misunderstanding_lines,
        "recent_free_texts": free_text_lines,
        "next_directions": next_direction_lines,
        "report_text": report_text,
    }


def _profile_dimensions(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item)[:80] for item in raw if str(item).strip()][:8]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [part.strip()[:80] for part in raw.split(",") if part.strip()][:8]
        if isinstance(parsed, list):
            return [str(item)[:80] for item in parsed if str(item).strip()][:8]
    return ["long_term_interest", "reading_preference"]


def _json_loads(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except json.JSONDecodeError:
        return default


def _float_score(raw: Any, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def _preferred_source_url(current_url: str, sources: list[Any]) -> str:
    if is_preferred_book_landing_url(current_url):
        return current_url
    source_type_order = {
        "official_page": 0,
        "sample_chapter": 1,
        "table_of_contents": 2,
        "public_page": 3,
        "review": 4,
    }
    candidates = []
    for source in sources:
        try:
            url = str(source["url"] or "")
            title = str(source["title"] or "")
            source_type = str(source["source_type"] or "")
        except (KeyError, TypeError, IndexError):
            url = str(getattr(source, "url", "") or "")
            title = str(getattr(source, "title", "") or "")
            source_type = str(getattr(source, "source_type", "") or "")
        if not url or not is_preferred_book_landing_url(url, title):
            continue
        candidates.append((source_type_order.get(source_type, 99), url))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def build_daily_profile_context(
    structured_profile_context: str,
    long_term_memory_context: str,
    hermes_native_profile_context: str = "",
) -> str:
    return build_prioritized_daily_profile_context(
        structured_profile_context=structured_profile_context,
        long_term_memory_context=long_term_memory_context,
        hermes_native_profile_context=hermes_native_profile_context,
    )


def build_recommendation_history_context(repo: Repository, days: int = 60, limit: int = 20) -> str:
    recommendations = repo.recent_recommendations(days=days)[:limit]
    feedback_rows = repo.reflection_feedback_events(days=days, limit=limit * 2)
    if not recommendations and not feedback_rows:
        return EMPTY_RECOMMENDATION_HISTORY_CONTEXT

    feedback_by_recommendation: dict[int, list[Any]] = {}
    for row in feedback_rows:
        feedback_by_recommendation.setdefault(int(row["recommendation_id"]), []).append(row)

    hard_exclusions: list[str] = []
    cooldown_exact_titles: list[str] = []
    negative_signals: list[str] = []
    positive_anchors: list[str] = []
    neutral_signals: list[str] = []
    recent_lines: list[str] = []
    theme_counts: dict[str, int] = {}
    title_counts: dict[tuple[str, str], int] = {}
    title_labels: dict[tuple[str, str], str] = {}
    feedback_type_counts: dict[str, int] = {}
    feedback_reason_counts: dict[str, int] = {}
    negative_theme_counts: dict[str, int] = {}
    positive_theme_counts: dict[str, int] = {}

    for row in recommendations:
        recommendation_id = int(row["id"])
        title = str(row["title"] or "")
        author = str(row["author"] or "")
        theme = str(row["theme"] or "")
        slot_type = str(row["slot_type"] or "")
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
        key = _book_key(title, author)
        title_counts[key] = title_counts.get(key, 0) + 1
        title_labels[key] = f"{title} / {author}"
        feedback = feedback_by_recommendation.get(recommendation_id, [])
        feedback_summary = _recommendation_feedback_summary(feedback)
        recent_lines.append(
            f"- {title} / {author} | theme={theme} | slot={slot_type} | feedback={feedback_summary or 'none'}"
        )
        cooldown_exact_titles.append(f"- {title} / {author}: recommended recently; avoid exact repeat unless user explicitly asks")
        if any(str(item["feedback_type"]) == "already_read" for item in feedback):
            hard_exclusions.append(f"- {title} / {author}: user marked already_read")
        if any(str(item["feedback_type"]) == "not_interested" for item in feedback):
            negative_signals.append(f"- {title} / {author}: {_recommendation_feedback_summary(feedback)}")
            negative_theme_counts[theme] = negative_theme_counts.get(theme, 0) + 1
        if any(str(item["feedback_type"]) == "neutral" for item in feedback):
            neutral_signals.append(f"- {title} / {author}: {_recommendation_feedback_summary(feedback)}")
        if any(str(item["feedback_type"]) in {"like", "go_deeper"} for item in feedback):
            positive_anchors.append(f"- {title} / {author}: {_recommendation_feedback_summary(feedback)}")
            positive_theme_counts[theme] = positive_theme_counts.get(theme, 0) + 1

    for row in feedback_rows:
        feedback_type = str(row["feedback_type"] or "")
        reason_code = str(row["reason_code"] or "")
        if feedback_type:
            feedback_type_counts[feedback_type] = feedback_type_counts.get(feedback_type, 0) + 1
        if reason_code:
            feedback_reason_counts[reason_code] = feedback_reason_counts.get(reason_code, 0) + 1

    repeated_themes = [
        f"- {theme}: recommended {count} times in recent {days} days"
        for theme, count in sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))
        if theme and count >= 2
    ]
    repeated_titles = [
        f"- {title_labels[key]}: recommended {count} times in recent {days} days"
        for key, count in sorted(title_counts.items(), key=lambda item: (-item[1], title_labels.get(item[0], "")))
        if key[0] and count >= 2
    ]
    feedback_distribution = _feedback_distribution_lines(feedback_type_counts, feedback_reason_counts)
    positive_theme_lines = _theme_signal_lines(positive_theme_counts, days, "positive feedback")
    negative_theme_lines = _theme_signal_lines(negative_theme_counts, days, "negative feedback")

    sections = [
        "RecommendationHistoryContext:",
        "",
        "Window summary:",
        f"- Lookback days: {days}",
        f"- Recent recommendations included: {len(recommendations)}",
        f"- Feedback events included: {len(feedback_rows)}",
        f"- Hard exclusions: {len(hard_exclusions)}",
        f"- Recent exact-title cooldowns: {len(cooldown_exact_titles)}",
        "",
        "Hard exclusions:",
        *(hard_exclusions[:8] or ["- None."]),
        "",
        "Recent exact-title cooldown:",
        *(cooldown_exact_titles[:12] or ["- None."]),
        "",
        "Negative feedback:",
        *(negative_signals[:8] or ["- None."]),
        "",
        "Neutral / weak-fit feedback:",
        *(neutral_signals[:6] or ["- None."]),
        "",
        "Positive anchors:",
        *(positive_anchors[:8] or ["- None."]),
        "",
        "Feedback distribution:",
        *feedback_distribution,
        "",
        "History fatigue:",
        *(repeated_themes[:6] or ["- None."]),
        "",
        "Repeated exact-title signals:",
        *(repeated_titles[:6] or ["- None."]),
        "",
        "Positive theme signals:",
        *(positive_theme_lines[:6] or ["- None."]),
        "",
        "Negative theme signals:",
        *(negative_theme_lines[:6] or ["- None."]),
        "",
        "Recent recommendations:",
        *recent_lines[:limit],
        "",
        "Hermes selection instruction:",
        "- Do not recommend hard exclusions.",
        "- Avoid recent exact-title cooldown items even if they are not already_read.",
        "- Treat negative feedback as a semantic avoidance signal, not just exact-title exclusion.",
        "- Treat neutral feedback and weak-fit reasons as evidence to adjust angle, difficulty, timing, or source quality.",
        "- Use positive anchors to find adjacent books, but avoid repeating the same title or theme too frequently.",
        "- Prefer a mixed slate: stable profile-fit classics plus one exploration only when history does not show fatigue.",
        "- Include history_check in each candidate when possible.",
    ]
    return "\n".join(sections)


def _feedback_distribution_lines(feedback_type_counts: dict[str, int], feedback_reason_counts: dict[str, int]) -> list[str]:
    if not feedback_type_counts and not feedback_reason_counts:
        return ["- None."]
    lines = [
        f"- type={FEEDBACK_LABELS.get(feedback_type, feedback_type)} ({feedback_type}): {count}"
        for feedback_type, count in sorted(feedback_type_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    reason_lines = [
        f"- reason={FEEDBACK_REASON_LABELS.get(reason_code, reason_code)} ({reason_code}): {count}"
        for reason_code, count in sorted(feedback_reason_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return lines[:6] + reason_lines[:8]


def _theme_signal_lines(theme_counts: dict[str, int], days: int, label: str) -> list[str]:
    return [
        f"- {theme}: {count} {label} event(s) in recent {days} days"
        for theme, count in sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))
        if theme
    ]


def _recommendation_hard_exclusion_keys(repo: Repository, feedback_days: int = 365, recent_days: int = 14) -> set[tuple[str, str]]:
    keys = {
        _book_key(str(row["title"] or ""), str(row["author"] or ""))
        for row in repo.reflection_feedback_events(days=feedback_days, limit=500)
        if str(row["feedback_type"] or "") == "already_read"
    }
    keys.update(
        _book_key(str(row["title"] or ""), str(row["author"] or ""))
        for row in repo.recent_recommendations(days=recent_days)
    )
    return {key for key in keys if key[0]}


def _book_key(title: str, author: str) -> tuple[str, str]:
    return (" ".join(title.lower().split()), " ".join(author.lower().split()))


def _recommendation_feedback_summary(feedback_rows: list[Any]) -> str:
    pieces = []
    for row in feedback_rows[:4]:
        feedback_type = str(row["feedback_type"] or "")
        reason_code = str(row["reason_code"] or "")
        free_text = str(row["free_text"] or "").strip()
        label = FEEDBACK_LABELS.get(feedback_type, feedback_type)
        reason = FEEDBACK_REASON_LABELS.get(reason_code, reason_code)
        text = f"{label}"
        if reason:
            text += f"/{reason}"
        if free_text:
            text += f": {free_text[:80]}"
        pieces.append(text)
    return "; ".join(pieces)


def _dimension_type_label(dimension_type: str) -> str:
    labels = {
        "exploration": "探索型",
        "profile_fit": "画像贴合",
        "knowledge_gap": "知识缺口",
    }
    return labels.get(dimension_type, dimension_type)


def _profile_confidence_sections(profile_items, misunderstanding_signals) -> dict[str, list[str]]:
    stable = []
    pending = []
    new_signals = []
    for row in profile_items:
        evidence_count = int(row["evidence_count"])
        confidence = float(row["confidence"])
        line = _profile_item_line(row)
        if evidence_count >= 3 and confidence >= 0.55:
            stable.append(line)
        else:
            pending.append(line)
        if bool(row["is_recently_created"]) or evidence_count == 1:
            new_signals.append(line)

    misunderstood = [
        _profile_item_line(row, _misunderstanding_signal_summary(row, misunderstanding_signals))
        for row in profile_items
        if _profile_has_misunderstanding_signal(row, misunderstanding_signals)
    ]
    return {
        "stable": stable or ["- 暂无稳定画像。"],
        "pending": pending or ["- 暂无待验证画像。"],
        "new": new_signals or ["- 最近 7 天暂无新画像信号。"],
        "misunderstood": misunderstood or ["- 暂无画像级可能误解。"],
    }


def _profile_item_line(row, misunderstanding_summary: str = "") -> str:
    category = PROFILE_CATEGORIES.get(row["category"], row["category"])
    parts = [
        f"category={category}",
        f"content={row['content']}",
        f"confidence={float(row['confidence']):.2f}",
        f"evidence_count={int(row['evidence_count'])}",
        f"最近证据={_latest_evidence_summary(row)}",
    ]
    if misunderstanding_summary:
        parts.append(f"误解信号={misunderstanding_summary}")
    return "- " + "; ".join(parts)


def _latest_evidence_summary(row) -> str:
    try:
        evidence_list = json.loads(row["evidence_json"] or "[]")
    except json.JSONDecodeError:
        return "证据格式异常"
    if not isinstance(evidence_list, list) or not evidence_list:
        return "暂无证据"

    latest = evidence_list[-1]
    if not isinstance(latest, dict):
        return str(latest)[:120]
    source = str(latest.get("source", "unknown"))
    if source == "feedback":
        feedback_type = str(latest.get("feedback_type", ""))
        reason_code = str(latest.get("reason_code", ""))
        label = FEEDBACK_LABELS.get(feedback_type, feedback_type or "反馈")
        reason = FEEDBACK_REASON_LABELS.get(reason_code, reason_code)
        theme = str(latest.get("theme", "")).strip()
        book = str(latest.get("book", "")).strip()
        pieces = [f"feedback:{label}"]
        if reason:
            pieces.append(reason)
        if theme:
            pieces.append(f"theme={theme}")
        if book:
            pieces.append(f"book={book}")
        return " / ".join(pieces)[:160]
    text = str(latest.get("text") or latest.get("free_text") or latest)[:120]
    return f"{source}:{text}"


def _profile_has_misunderstanding_signal(row, signals) -> bool:
    return bool(_matching_misunderstanding_signals(row, signals))


def _misunderstanding_signal_summary(row, signals) -> str:
    matched = _matching_misunderstanding_signals(row, signals)
    summaries = []
    for signal in matched[:3]:
        reason_code = signal["reason_code"]
        reason_label = FEEDBACK_REASON_LABELS.get(reason_code, reason_code or signal["feedback_type"])
        summaries.append(f"{signal['theme']} / {reason_label} x{signal['count']}")
    return "；".join(summaries)


def _matching_misunderstanding_signals(row, signals) -> list:
    matches = []
    for signal in signals:
        count = int(signal["count"])
        negative_count = int(signal["negative_count"])
        reason_code = signal["reason_code"]
        if negative_count < 2 and count < 2 and reason_code not in MISUNDERSTANDING_REASON_CODES:
            continue
        if _profile_matches_theme(row, signal["theme"]):
            matches.append(signal)
    return matches


def _profile_matches_theme(row, theme: str) -> bool:
    content = _normalize_profile_content(str(row["content"]))
    theme = str(theme).strip()
    if not content or not theme:
        return False
    return content in theme or theme in content


def _normalize_profile_content(content: str) -> str:
    prefixes = (
        "短期避免：",
        "已掌握：",
        "需要降低难度：",
        "偏好更实战：",
        "偏好可复用方法论：",
        "当前正在解决：",
        "当前问题相关缺口：",
        "已读或熟悉：",
    )
    normalized = content.strip()
    for prefix in prefixes:
        if normalized.startswith(prefix):
            return normalized[len(prefix) :].strip()
    return normalized


def _misunderstanding_lines(rows) -> list[str]:
    if not rows:
        return ["- 暂无明显误解信号；继续观察低反馈或无反馈推荐。"]
    lines = []
    for row in rows:
        reason_code = row["reason_code"]
        theme = row["theme"]
        count = row["count"]
        if reason_code == "already_know":
            message = f"可能低估了你在“{theme}”上的已有背景。"
        elif reason_code == "too_theoretical":
            message = f"“{theme}”方向可能给得太理论，应该增加实践案例。"
        elif reason_code == "too_hard":
            message = f"“{theme}”方向可能跨度过大，需要降低难度或补前置知识。"
        elif reason_code == "wrong_timing":
            message = f"“{theme}”可能不是当前时机，短期优先级应下调。"
        elif reason_code == "topic_irrelevant":
            message = f"“{theme}”可能偏离当前真实关注点。"
        elif reason_code == "too_marketing":
            message = f"“{theme}”内容可能营销感过强，应优先选择一手资料或硬核案例。"
        else:
            label = FEEDBACK_REASON_LABELS.get(reason_code, reason_code)
            message = f"“{theme}”收到 {label} 信号，需要复核推荐假设。"
        lines.append(f"- {message}（{count} 次）")
    return lines


def _free_text_summary_lines(rows) -> list[str]:
    if not rows:
        return ["- 暂无自由文本补充。"]
    lines = []
    for row in rows[:3]:
        feedback_label = FEEDBACK_LABELS.get(row["feedback_type"], row["feedback_type"])
        reason_label = FEEDBACK_REASON_LABELS.get(row["reason_code"], row["reason_code"])
        reason = f" / {reason_label}" if reason_label else ""
        text = " ".join(str(row["free_text"]).split())[:120]
        safe_text = escape(text, quote=False)
        lines.append(f"- {row['theme']} / {feedback_label}{reason}: {safe_text}")
    return lines


def _user_weekly_summary_lines(
    recommendation_count: int,
    feedback_total: int,
    positive_total: int,
    hit_rate: float,
    profile_sections: dict[str, list[str]],
    misunderstanding_lines: list[str],
    next_direction_lines: list[str],
) -> list[str]:
    lines = [
        f"- 这 7 天系统一共给你推了 {recommendation_count} 本书，收到 {feedback_total} 次反馈；其中 {positive_total} 次可以视为正向信号，粗略命中率是 {hit_rate}%。"
    ]
    stable = _first_real_line(profile_sections.get("stable", []))
    pending = _first_real_line(profile_sections.get("pending", []))
    misunderstood = _first_real_line(profile_sections.get("misunderstood", []))
    if stable:
        lines.append(f"- 目前相对稳定的画像是：{_humanize_profile_line(stable)}")
    elif pending:
        lines.append(f"- 目前还没有足够稳定的画像，但有一个值得继续验证的方向：{_humanize_profile_line(pending)}")
    else:
        lines.append("- 目前画像证据还偏少，更适合把下周当成校准周，而不是急着给你贴长期标签。")

    if misunderstood:
        lines.append(f"- 有一个画像可能需要修正：{_humanize_profile_line(misunderstood)}")
    else:
        signal = _first_real_line(misunderstanding_lines)
        if signal:
            lines.append(f"- 系统暂时没有发现强误解，但仍会观察这个信号：{signal.removeprefix('- ').strip()}")

    direction = _first_real_line(next_direction_lines)
    if direction:
        lines.append(f"- 下周推荐策略建议：{direction.removeprefix('- ').strip()}")
    return lines


def _profile_writeback_lines(feedback_processing, hermes_profile_update_counts, reflection_status_counts) -> list[str]:
    total = int(feedback_processing["total_count"] or 0)
    processed = int(feedback_processing["processed_count"] or 0)
    pending = int(feedback_processing["pending_count"] or 0)
    hermes_counts = {row["status"]: int(row["count"]) for row in hermes_profile_update_counts}
    reflection_counts = {row["status"]: int(row["count"]) for row in reflection_status_counts}

    lines = []
    if total == 0:
        lines.append("- 本周没有 feedback 事件，所以没有发生“反馈驱动”的 ARC structured profile 写回。")
        lines.append("- Hermes 主画像也没有收到 feedback.ingest 写回请求；如果画像变化了，来源更可能是自动 reflection。")
    else:
        lines.append(f"- ARC structured profile：本周 {total} 条反馈中，已处理 {processed} 条，待处理 {pending} 条。")
        if hermes_counts:
            parts = "，".join(f"{status} {count}" for status, count in sorted(hermes_counts.items()))
            lines.append(f"- Hermes native USER profile：feedback.ingest 审计结果为 {parts}。")
        else:
            lines.append("- Hermes native USER profile：没有查到 feedback.ingest 审计记录，需要确认 run-daily 是否已处理这些反馈。")

    if reflection_counts:
        parts = "，".join(f"{status} {count}" for status, count in sorted(reflection_counts.items()))
        lines.append(f"- Reflection memory：本周反思记录状态为 {parts}。applied 表示已写入 memory/USER.md 和 memory/MEMORY.md。")
    else:
        lines.append("- Reflection memory：本周没有生成反思记录。")
    return lines


def _first_real_line(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("- 暂无"):
            return stripped
    return ""


def _humanize_profile_line(line: str) -> str:
    text = line.removeprefix("- ").strip()
    fields = {}
    for part in text.split("; "):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value
    category = fields.get("category", "画像")
    content = fields.get("content", "")
    confidence = fields.get("confidence", "")
    evidence_count = fields.get("evidence_count", "")
    evidence = fields.get("最近证据", "")
    summary = f"{category}：{content}" if content else text
    details = []
    if confidence:
        details.append(f"置信度 {confidence}")
    if evidence_count:
        details.append(f"{evidence_count} 条证据")
    if evidence:
        details.append(f"最近证据是 {evidence}")
    if details:
        summary += "（" + "，".join(details) + "）"
    return summary


def _next_direction_lines(positive_theme_counts, recent_profiles, feedback_total: int) -> list[str]:
    lines = [
        f"- 继续保留 2 条画像贴合推荐 + 1 条探索推荐，下一轮用反馈率校准比例。"
    ]
    if positive_theme_counts:
        themes = "、".join(row["theme"] for row in positive_theme_counts[:3])
        lines.append(f"- 优先沿着正反馈主题加深：{themes}。")
    if recent_profiles:
        dimensions = []
        for row in recent_profiles:
            label = PROFILE_CATEGORIES.get(row["category"], row["category"])
            if label not in dimensions:
                dimensions.append(label)
        if dimensions:
            lines.append(f"- 围绕近期变化明显的画像维度设计推荐：{'、'.join(dimensions[:3])}。")
    if feedback_total == 0:
        lines.append("- 本周暂无反馈，应先降低推荐假设复杂度，并明确邀请用户选择原因。")
    else:
        lines.append("- 对出现负向原因的主题，下一轮只保留一本验证，不要连续重复推送。")
    return lines
