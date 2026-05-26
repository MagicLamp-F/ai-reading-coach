from __future__ import annotations

import json
import logging
from datetime import datetime
from html import escape
from typing import Any

from app.feedback import FEEDBACK_LABELS, FEEDBACK_REASON_LABELS, FEEDBACK_TYPES, build_feedback_url
from app.lark import LarkFeedbackLink, LarkRobotClient
from app.llm import OpenAIChatClient
from app.profile import PROFILE_CATEGORIES, build_profile_context, process_feedback
from app.repository import RecommendationDraft, Repository
from app.search import SearchResult, TavilySearch
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

    def run_daily_recommendations(self) -> int:
        run_id = self.repo.create_run("daily_recommendation", {"channel": self.channel})
        api_calls = 0
        try:
            processed_feedback = process_feedback(self.repo)
            profile_context = build_profile_context(self.repo)
            themes = self._generate_themes(profile_context)
            if self.llm.api_key:
                api_calls += 1
                self.repo.record_cost(run_id, "model", "generate_themes", 1, {"model": self.llm.model})

            search_results: list[SearchResult] = []
            for theme in themes[:3]:
                if api_calls >= self.max_daily_api_calls:
                    break
                try:
                    results = self.search.search_books(f"{theme} 推荐 书籍 目录 书评", max_results=4)
                except Exception:
                    logger.exception("Search failed for theme=%s; continuing without those results", theme)
                    continue
                if results:
                    search_results.extend(results)
                    api_calls += 1
                    self.repo.record_cost(run_id, "tavily", "search_books", 1, {"theme": theme})

            drafts = self._generate_recommendations(profile_context, themes, search_results)
            if self.llm.api_key:
                api_calls += 1
                self.repo.record_cost(run_id, "model", "generate_recommendations", 1, {"model": self.llm.model})

            today = datetime.now().date()
            total = min(3, len(drafts))
            sent_drafts: list[RecommendationDraft] = []
            for index, draft in enumerate(drafts[:3], start=1):
                recommendation_id = self.repo.add_recommendation(run_id, draft, today)
                message_id = self._send_recommendation(index, total, recommendation_id, draft)
                if message_id is None and self._recommendation_channel_enabled():
                    raise RuntimeError(f"recommendation send failed: recommendation_id={recommendation_id}")
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

    def _send_recommendation(self, index: int, total: int, recommendation_id: int, draft: RecommendationDraft) -> str | None:
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
        return self.lark.send_recommendation(index, total, draft, links)

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
        if self.channel != "lark" or not self.lark.enabled() or len(drafts) < 3:
            return
        try:
            message_id = self.lark.send_profile_test_summary(drafts[:3])
        except Exception as exc:
            warning = f"profile test summary lark send failed: {exc}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return
        if message_id:
            return
        warning = "profile test summary lark send failed"
        logger.warning(warning)
        self.repo.record_run_warning(run_id, warning)

    def _generate_themes(self, profile_context: str) -> list[str]:
        try:
            response = self.llm.complete_json(
                "你是读书推荐系统的画像决策层。只输出 JSON。",
                (
                    "根据用户画像生成今日推荐主题。要求 2 个贴合画像主题，1 个探索型主题。"
                    '输出格式：{"themes":["主题1","主题2","主题3"]}\n\n'
                    f"用户画像：\n{profile_context}"
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
    ) -> list[RecommendationDraft]:
        search_context = "\n".join(
            f"- {result.title}\n  {result.url}\n  {result.content[:300]}"
            for result in search_results[:12]
        )
        try:
            response = self.llm.complete_json(
                "你是读书私教系统的执行层。只输出 JSON，不要输出 Markdown。",
                (
                    "基于用户画像、今日主题和搜索结果，推荐 3 本书。"
                    "每本书必须包含 title, author, source_url, slot_type, theme, system_hypothesis, "
                    "profile_dimensions, recommendation_reason, profile_mapping, expected_benefit, risk, reading_suggestion。"
                    "system_hypothesis 说明这本书正在测试哪个用户假设；profile_dimensions 是画像维度字符串数组。"
                    "slot_type 只能是 profile_fit 或 exploration。"
                    '输出格式：{"books":[...]}。\n\n'
                    f"用户画像：\n{profile_context}\n\n"
                    f"今日主题：{json.dumps(themes, ensure_ascii=False)}\n\n"
                    f"搜索结果：\n{search_context}"
                ),
            )
        except Exception:
            logger.exception("Recommendation generation failed; using fallback books")
            return [self._draft_from_dict(item) for item in FALLBACK_BOOKS]
        books = response.get("books") if isinstance(response, dict) else None
        if isinstance(books, list) and books:
            drafts = [self._draft_from_dict(item) for item in books[:3] if isinstance(item, dict)]
            if drafts:
                return drafts
        return [self._draft_from_dict(item) for item in FALLBACK_BOOKS]

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
            metadata={"source": "llm_or_fallback"},
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
