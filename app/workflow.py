from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from app.feedback import FEEDBACK_LABELS, FEEDBACK_REASON_LABELS, FEEDBACK_TYPES, build_feedback_url, build_reading_pack_url
from app.daily_agent_adapter import DailyRecommendationAgentAdapter
from app.lark import LarkFeedbackLink, LarkRobotClient
from app.llm import OpenAIChatClient
from app.memory import DEFAULT_LONG_TERM_MEMORY_MAX_CHARS, load_long_term_memory_context
from app.profile import PROFILE_CATEGORIES, build_profile_context, process_feedback
from app.reading_pack import FastReadPackService, HermesReadingPackAdapter, ReadingPackPreview
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

    def run_daily_recommendations(self) -> int:
        run_id = self.repo.create_run("daily_recommendation", {"channel": self.channel})
        api_calls = 0
        try:
            processed_feedback = process_feedback(self.repo)
            profile_context = build_daily_profile_context(
                structured_profile_context=build_profile_context(self.repo),
                long_term_memory_context=load_long_term_memory_context(self.memory_dir, self.max_memory_chars),
            )
            themes = self._generate_themes(profile_context)
            if self.daily_recommendation_agent is None and self.llm.api_key:
                api_calls += 1
                self.repo.record_cost(run_id, "model", "generate_themes", 1, {"model": self.llm.model})

            search_results: list[SearchResult] = []
            for theme in themes[:3]:
                if api_calls >= self.max_daily_api_calls:
                    break
                try:
                    results = self.search.search_books(
                        f"{theme} 经典 名著 高口碑 文学 科幻 书籍 目录 书评",
                        max_results=4,
                    )
                except Exception:
                    logger.exception("Search failed for theme=%s; continuing without those results", theme)
                    continue
                if results:
                    search_results.extend(results)
                    api_calls += 1
                    self.repo.record_cost(run_id, "tavily", "search_books", 1, {"theme": theme})

            recommendation_limit = (
                self.source_aware_candidate_count
                if self.source_aware_recommendations
                else self.daily_recommendation_count
            )
            drafts = self._generate_recommendations(profile_context, themes, search_results, recommendation_limit)
            drafts = self._source_aware_rank_drafts(run_id, drafts)
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

    @property
    def max_daily_api_calls(self) -> int:
        return self.max_search_calls + self.max_model_calls

    def build_weekly_report(self) -> str:
        days = 7
        recommendation_count = self.repo.weekly_recommendation_count(days)
        feedback_type_counts = self.repo.weekly_feedback_type_counts(days)
        reason_code_counts = self.repo.weekly_reason_code_counts(days)
        dimension_counts = self.repo.weekly_feedback_dimension_counts(days)
        positive_theme_counts = self.repo.weekly_positive_theme_counts(days)
        misread_signal_counts = self.repo.weekly_misread_signal_counts(days)
        recent_profiles = self.repo.recent_profile_updates(days, limit=8)
        profile_items = self.repo.profile_items_for_report(days, limit=40)
        profile_misunderstanding_signals = self.repo.weekly_profile_misunderstanding_signals(days)
        recent_free_texts = self.repo.recent_feedback_free_texts(days, limit=3)
        enhanced_dimensions = self.repo.recent_profile_dimension_counts(days)

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
        return (
            "7 天画像复盘\n\n"
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
            message_id = self._send_recommendation(index, total, int(recommendation_id), draft, None)
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
                agent=self.reading_pack_agent,
                source_collector=self.source_collector,
            ).generate_for_recommendation(recommendation_id)
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

    def _generate_themes(self, profile_context: str) -> list[str]:
        if self.daily_recommendation_agent is not None:
            try:
                return self.daily_recommendation_agent.generate_themes(profile_context)
            except Exception:
                logger.exception("Hermes daily theme generation failed; using default themes")
                return DEFAULT_THEMES
        try:
            response = self.llm.complete_json(
                "你是读书推荐系统的画像决策层。只输出 JSON。",
                (
                    "根据用户画像上下文生成今日推荐主题。要求 2 个贴合画像主题，1 个探索型主题。"
                    "如果画像显示用户偏好经典名著、文学、科幻或高口碑作品，主题必须明显覆盖这些方向，"
                    "不要只生成工程技术、商业或工具书主题。"
                    "用户画像上下文明确分为 SQLite structured profile 和 Hermes long-term memory；"
                    "二者都可使用，但不要假设未出现在上下文中的 draft reflection 已生效。"
                    '输出格式：{"themes":["主题1","主题2","主题3"]}\n\n'
                    f"用户画像上下文：\n{profile_context}"
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
    ) -> list[RecommendationDraft]:
        if self.daily_recommendation_agent is not None:
            try:
                books = self.daily_recommendation_agent.generate_recommendations(
                    profile_context,
                    themes,
                    search_results,
                    max_books=max_books,
                )
                drafts = [self._draft_from_dict(item) for item in books[:max_books] if isinstance(item, dict)]
                if drafts:
                    return drafts
            except Exception:
                logger.exception("Hermes daily recommendation generation failed; using fallback books")
            return [self._draft_from_dict(item) for item in FALLBACK_BOOKS]

        search_context = "\n".join(
            f"- {result.title}\n  {result.url}\n  {result.content[:300]}"
            for result in search_results[:12]
        )
        try:
            response = self.llm.complete_json(
                "你是读书私教系统的执行层。只输出 JSON，不要输出 Markdown。",
                (
                    "用户画像上下文明确分为 SQLite structured profile 和 Hermes long-term memory；"
                    "二者都可使用，但不要假设未出现在上下文中的 draft reflection 已生效。"
                    f"基于用户画像上下文、今日主题和搜索结果，输出 {max_books} 本候选书。"
                    "优先推荐真正的书，尤其是经典名著、高口碑文学、严肃小说、科幻经典或长期被讨论的作品；"
                    "如果用户提到《一句顶一万句》《三体》这类偏好，应优先选择相近气质或同等口碑的书。"
                    "不要把云厂商文章、博客文章、课程页或普通技术文章当作书籍来源。"
                    "每本书必须包含 title, author, source_url, slot_type, theme, system_hypothesis, "
                    "profile_dimensions, recommendation_reason, profile_mapping, expected_benefit, risk, reading_suggestion。"
                    "建议额外包含 user_fit_score 和 candidate_reason。"
                    "system_hypothesis 说明这本书正在测试哪个用户假设；profile_dimensions 是画像维度字符串数组。"
                    "slot_type 只能是 profile_fit 或 exploration。"
                    '输出格式：{"books":[...]}。\n\n'
                    f"用户画像上下文：\n{profile_context}\n\n"
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


def build_daily_profile_context(structured_profile_context: str, long_term_memory_context: str) -> str:
    return (
        "SQLite structured profile:\n"
        f"{structured_profile_context.strip() or '暂无画像。'}\n\n"
        "Hermes long-term memory:\n"
        f"{long_term_memory_context.strip() or '暂无 Hermes long-term memory。'}"
    )


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
