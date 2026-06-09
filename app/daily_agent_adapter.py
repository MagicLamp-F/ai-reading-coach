from __future__ import annotations

import json
import logging
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.search import SearchResult

logger = logging.getLogger(__name__)

INTENT_PROFILE_CONTEXT_MAX_CHARS = 5000
EFFECTIVE_PROFILE_SUMMARY_MAX_LINES = 12
THEME_INTENT_SCHEMA_VERSION = "themes_v2"
RECOMMENDATION_PLAN_SCHEMA_VERSION = "recommendation_plan_v1"
RECOMMENDATION_REVIEW_SCHEMA_VERSION = "recommendation_review_v1"
AGENTIC_SHADOW_SCHEMA_VERSION = "agentic_shadow_v1"
DAILY_AGENT_RUNTIME_CAPABILITY_SCHEMA_VERSION = "daily_agent_runtime_capabilities_v1"

THEME_GENERATION_RULES = (
    "Theme generation rules:\n"
    "- Output exactly 3 themes.\n"
    "- The first 2 themes must be profile_fit themes; the third must be an exploration theme.\n"
    "- At least one theme must clearly cover classic/high-reputation literature or Chinese literary classics.\n"
    "- At least one theme must clearly cover classic science fiction, especially civilization imagination, "
    "technology ethics, or future society.\n"
    "- Do not output only engineering, business, productivity, or tool-book themes.\n"
    "- Downrank software engineering and AI Agent commercialization if they appear as recent high-frequency "
    "themes without fresh positive feedback.\n"
    "- Themes must be concrete enough to guide downstream book selection.\n"
    "- Avoid semantic duplicates of recent high-frequency themes unless positive feedback exists for that exact "
    "theme cluster."
)


@dataclass(frozen=True)
class ThemeIntent:
    theme: str
    slot: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "theme": self.theme,
            "slot": self.slot,
            "reason": self.reason,
        }


class DailyAgentAdapterError(RuntimeError):
    pass


class DailyRecommendationAgentAdapter(Protocol):
    name: str

    def generate_themes(self, profile_context: str, recommendation_history_context: str = "") -> list[str]:
        ...

    def generate_recommendations(
        self,
        profile_context: str,
        themes: list[str],
        search_results: list[SearchResult],
        max_books: int = 3,
        recommendation_history_context: str = "",
    ) -> list[dict[str, Any]]:
        ...

    def review_recommendations(
        self,
        profile_context: str,
        recommendation_history_context: str,
        themes: list[str],
        generated_candidates: list[dict[str, Any]],
        selected_recommendations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...

    def agentic_shadow_recommendations(
        self,
        profile_context: str,
        recommendation_history_context: str,
        themes: list[str],
        recommendation_plan: dict[str, Any] | None,
        generated_candidates: list[dict[str, Any]],
        selected_recommendations: list[dict[str, Any]],
        shadow_config: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class HermesDailyRecommendationAdapter:
    name = "hermes-agent"

    def __init__(
        self,
        command: str = "/home/ubuntu/projects/hermes-agent/bin/reflect-json",
        timeout_seconds: float = 60.0,
        runner=subprocess.run,
    ):
        self.command = command.strip()
        self.timeout_seconds = timeout_seconds
        self.runner = runner
        self._local_session: dict[str, Any] | None = None
        self._last_theme_intents: list[ThemeIntent] = []

    def start_local_session(self, run_id: int, purpose: str = "run_daily") -> None:
        self._local_session = {
            "session_id": f"arc-{purpose}-{run_id}",
            "scope": purpose,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "persistence": "bounded_to_current_arc_run",
            "hermes_internal_thread": "not_supported_by_current_reflect_json_wrapper",
            "turns": [],
        }

    def runtime_capabilities(self) -> dict[str, Any]:
        return {
            "schema_version": DAILY_AGENT_RUNTIME_CAPABILITY_SCHEMA_VERSION,
            "provider": self.name,
            "runtime": "reflect-json",
            "supports_native_thread": False,
            "supports_delegation": False,
            "supports_memory": False,
            "supports_file": False,
            "supports_terminal": False,
            "supports_web": False,
            "supports_session_search": False,
            "side_effects_allowed": False,
        }

    def end_local_session(self) -> None:
        self._local_session = None

    def generate_themes(self, profile_context: str, recommendation_history_context: str = "") -> list[str]:
        response = self._call(
            {
                "route": "reading.recommend.intent",
                "domain": "reading",
                "tool_policy": "none",
                "output_schema": THEME_INTENT_SCHEMA_VERSION,
                "format": "json",
                "system_prompt": (
                    "你是读书推荐系统的 Hermes 画像决策层。只输出 JSON。"
                    "这是只读决策 route；不要修改文件、数据库、memory、消息或网络通道。"
                ),
                "user_prompt": (
                    "根据用户画像上下文和推荐历史生成今日推荐主题。要求 2 个贴合画像主题，1 个探索型主题。"
                    "如果画像显示用户偏好经典名著、文学、科幻或高口碑作品，主题必须明显覆盖这些方向，"
                    "避免重复最近高频主题，除非推荐历史显示用户明确正反馈。"
                    "不要只生成工程技术、商业或工具书主题。"
                    "主题必须能直接指导下游选书，不要输出过于抽象或无法映射到具体书籍的兴趣标签。"
                    f"\n\n{THEME_GENERATION_RULES}\n\n"
                    "输出格式严格为 "
                    '{"themes":[{"theme":"主题1","slot":"profile_fit","reason":"基于哪些画像证据"},'
                    '{"theme":"主题2","slot":"profile_fit","reason":"基于哪些画像证据"},'
                    '{"theme":"主题3","slot":"exploration","reason":"要验证什么新假设"}]}。'
                ),
                "context": {
                    "effective_profile_summary": build_effective_profile_summary(profile_context),
                    "profile_context": _bounded_text(profile_context, INTENT_PROFILE_CONTEXT_MAX_CHARS),
                    "recommendation_history_context": recommendation_history_context,
                    "local_session": self._local_session_context(),
                },
                "output_contract": {
                    "themes": [
                        {
                            "theme": "string",
                            "slot": "profile_fit|exploration",
                            "reason": "string",
                        }
                    ]
                },
                "constraints": _constraints(),
            }
        )
        intents = normalize_theme_intents(response.get("themes"))
        if not intents:
            raise DailyAgentAdapterError("Hermes returned no themes")
        self._last_theme_intents = intents
        normalized = [intent.theme for intent in intents]
        self._remember_local_turn(
            "reading.recommend.intent",
            {"profile_context_chars": len(profile_context), "history_context_chars": len(recommendation_history_context)},
            {"themes": normalized, "theme_intents": [intent.as_dict() for intent in intents]},
        )
        return normalized

    def plan_recommendations(
        self,
        profile_context: str,
        recommendation_history_context: str = "",
    ) -> dict[str, Any]:
        response = self._call(
            {
                "route": "reading.recommend.plan_v1",
                "domain": "reading",
                "tool_policy": "none",
                "output_schema": RECOMMENDATION_PLAN_SCHEMA_VERSION,
                "format": "json",
                "system_prompt": (
                    "你是读书推荐系统的 Hermes 推荐规划层。只输出 JSON。"
                    "这是只读 planning route；不要修改文件、数据库、memory、消息或网络通道。"
                ),
                "user_prompt": (
                    "根据用户画像上下文和推荐历史，为今日推荐规划 3 个 slot。"
                    "必须保持 2 个 profile_fit + 1 个 exploration。"
                    "每个 slot 输出 theme、search_queries、candidate_criteria、risk_controls 和 reason。"
                    "search_queries 必须适合公开搜索具体书籍，不要只给抽象标签。"
                    "candidate_criteria 要说明候选书需要满足什么条件；risk_controls 要说明如何避免 hard exclusions、"
                    "history fatigue、文章/课程误判、过度工程/商业/工具书推荐。"
                    "规划只能作为 ARC 的 hint；不要要求直接写库、投递或更新 memory。"
                    f"\n\n{THEME_GENERATION_RULES}\n\n"
                    '输出格式严格为 {"slots":[{"slot_type":"profile_fit","theme":"主题",'
                    '"search_queries":["query"],"candidate_criteria":["标准"],'
                    '"risk_controls":["控制"],"reason":"画像/历史依据"}],'
                    '"global_risk_controls":[],"plan_summary":"string","confidence":0.0}。'
                ),
                "context": {
                    "effective_profile_summary": build_effective_profile_summary(profile_context),
                    "profile_context": _bounded_text(profile_context, INTENT_PROFILE_CONTEXT_MAX_CHARS),
                    "recommendation_history_context": recommendation_history_context,
                    "local_session": self._local_session_context(),
                },
                "output_contract": {
                    "slots": [
                        {
                            "slot_type": "profile_fit|exploration",
                            "theme": "string",
                            "search_queries": ["string"],
                            "candidate_criteria": ["string"],
                            "risk_controls": ["string"],
                            "reason": "string",
                        }
                    ],
                    "global_risk_controls": ["string"],
                    "plan_summary": "string",
                    "confidence": "number 0..1",
                },
                "constraints": _constraints(),
            }
        )
        plan = normalize_recommendation_plan(response)
        slots = plan.get("slots", [])
        intents = [
            ThemeIntent(
                theme=str(slot.get("theme", ""))[:80],
                slot=_normalize_theme_slot(slot.get("slot_type"), "exploration" if index == 2 else "profile_fit"),
                reason=str(slot.get("reason", ""))[:240] or "Derived from recommendation_plan_v1.",
            )
            for index, slot in enumerate(slots[:3])
            if isinstance(slot, dict) and str(slot.get("theme", "")).strip()
        ]
        if intents:
            self._last_theme_intents = intents
        self._remember_local_turn(
            "reading.recommend.plan_v1",
            {"profile_context_chars": len(profile_context), "history_context_chars": len(recommendation_history_context)},
            {
                "themes": [intent.theme for intent in intents],
                "slot_count": len(slots),
                "confidence": plan.get("confidence", 0.0),
            },
        )
        return plan

    def generate_recommendations(
        self,
        profile_context: str,
        themes: list[str],
        search_results: list[SearchResult],
        max_books: int = 3,
        recommendation_history_context: str = "",
    ) -> list[dict[str, Any]]:
        search_context = "\n".join(
            f"- {result.title}\n  {result.url}\n  {result.content[:300]}"
            for result in search_results[:12]
        )
        response = self._call(
            {
                "route": "reading.recommend.generate",
                "domain": "reading",
                "tool_policy": "none",
                "output_schema": "recommendations_v1",
                "format": "json",
                "system_prompt": "你是读书私教系统的 Hermes 推荐筛选层。只输出 JSON，不要输出 Markdown。",
                "user_prompt": (
                    f"基于用户画像上下文、推荐历史、今日主题和搜索结果，筛选并输出 {max_books} 本候选书。"
                    "优先推荐真正的书，尤其是经典名著、高口碑文学、严肃小说、科幻经典或长期被讨论的作品；"
                    "如果用户提到《一句顶一万句》《三体》这类偏好，应优先选择相近气质或同等口碑的书。"
                    "必须遵守推荐历史中的 Hard exclusions；避免 History fatigue 中的重复主题。"
                    "不要把云厂商文章、博客文章、课程页或普通技术文章当作书籍来源。"
                    "每本书必须包含 title, author, source_url, slot_type, theme, system_hypothesis, "
                    "profile_dimensions, recommendation_reason, profile_mapping, expected_benefit, risk, reading_suggestion。"
                    "建议额外包含 user_fit_score、candidate_reason 和 history_check。"
                    "slot_type 只能是 profile_fit 或 exploration。"
                    '输出格式严格为 {"books":[...]}。'
                ),
                "context": {
                    "profile_context": profile_context,
                    "recommendation_history_context": recommendation_history_context,
                    "themes": themes,
                    "theme_intents": self._theme_intents_for_context(themes),
                    "search_results": search_context,
                    "local_session": self._local_session_context(),
                },
                "output_contract": {
                    "books": [
                        {
                            "title": "string",
                            "author": "string",
                            "source_url": "string",
                            "slot_type": "profile_fit|exploration",
                            "theme": "string",
                            "system_hypothesis": "string",
                            "profile_dimensions": ["string"],
                            "recommendation_reason": "string",
                            "profile_mapping": "string",
                            "expected_benefit": "string",
                            "risk": "string",
                            "reading_suggestion": "string",
                        }
                    ]
                },
                "constraints": _constraints(),
            }
        )
        books = response.get("books")
        if not isinstance(books, list) or not books:
            raise DailyAgentAdapterError("Hermes returned no recommendation books")
        normalized = [book for book in books if isinstance(book, dict)][:max_books]
        self._remember_local_turn(
            "reading.recommend.generate",
            {"theme_count": len(themes), "search_result_count": len(search_results), "max_books": max_books},
            {"books": [{"title": str(book.get("title", ""))[:120], "author": str(book.get("author", ""))[:120]} for book in normalized]},
        )
        return normalized

    def review_recommendations(
        self,
        profile_context: str,
        recommendation_history_context: str,
        themes: list[str],
        generated_candidates: list[dict[str, Any]],
        selected_recommendations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        response = self._call(
            {
                "route": "reading.recommend.review_v1",
                "domain": "reading",
                "tool_policy": "none",
                "output_schema": RECOMMENDATION_REVIEW_SCHEMA_VERSION,
                "format": "json",
                "system_prompt": (
                    "你是读书推荐系统的 Hermes 影子审查层。只输出 JSON，不要输出 Markdown。"
                    "这是只读 shadow route；不要修改文件、数据库、memory、消息或网络通道。"
                ),
                "user_prompt": (
                    "审查今日候选书和最终推荐是否符合用户画像、推荐历史和 ARC 业务约束。"
                    "重点检查：是否是真正的书而不是文章/课程/网页；是否命中 Hard exclusions 或历史疲劳；"
                    "是否满足 2 个 profile_fit + 1 个 exploration 的结构；是否给出可开始的阅读入口；"
                    "是否过度推荐工程、商业、工具书或重复大部头；是否和经典文学/科幻/高口碑书籍偏好冲突。"
                    "这是 shadow review，只能给出审查、风险和建议；不能要求直接写库、投递或更新 memory。"
                    '输出格式严格为 {"verdict":"accept|warn|reject","candidate_reviews":[...],'
                    '"global_warnings":[],"revision_instructions":[],"confidence":0.0}。'
                ),
                "context": {
                    "profile_context": profile_context,
                    "recommendation_history_context": recommendation_history_context,
                    "themes": themes,
                    "theme_intents": self._theme_intents_for_context(themes),
                    "generated_candidates": generated_candidates[:12],
                    "selected_recommendations": selected_recommendations[:6],
                    "local_session": self._local_session_context(),
                },
                "output_contract": {
                    "schema_version": RECOMMENDATION_REVIEW_SCHEMA_VERSION,
                    "verdict": "accept|warn|reject",
                    "candidate_reviews": [
                        {
                            "title": "string",
                            "author": "string",
                            "status": "keep|remove|replace|needs_check",
                            "reasons": ["string"],
                            "profile_fit_score": "number 0..1",
                            "fatigue_risk": "low|medium|high",
                            "start_path_quality": "good|weak|missing",
                            "resource_type_risk": "none|article_like|course_like|unknown",
                        }
                    ],
                    "global_warnings": ["string"],
                    "revision_instructions": ["string"],
                    "confidence": "number 0..1",
                },
                "constraints": _constraints(),
            }
        )
        review = normalize_recommendation_review(response)
        self._remember_local_turn(
            "reading.recommend.review_v1",
            {
                "generated_candidates": len(generated_candidates),
                "selected_recommendations": len(selected_recommendations),
            },
            {
                "verdict": review.get("verdict", ""),
                "candidate_review_count": len(review.get("candidate_reviews", [])),
            },
        )
        return review

    def agentic_shadow_recommendations(
        self,
        profile_context: str,
        recommendation_history_context: str,
        themes: list[str],
        recommendation_plan: dict[str, Any] | None,
        generated_candidates: list[dict[str, Any]],
        selected_recommendations: list[dict[str, Any]],
        shadow_config: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._call(
            {
                "route": "reading.recommend.agentic_shadow_v1",
                "domain": "reading",
                "tool_policy": "none",
                "output_schema": AGENTIC_SHADOW_SCHEMA_VERSION,
                "format": "json",
                "system_prompt": (
                    "你是读书推荐系统的 Hermes agentic shadow 评估层。只输出 JSON，不要输出 Markdown。"
                    "这是只读 shadow route；不要修改文件、数据库、memory、消息或网络通道。"
                    "当前 reflect-json runtime 不支持真实 delegation 时，也必须把输出标记为 simulated_trace。"
                ),
                "user_prompt": (
                    "基于用户画像、推荐历史、plan、候选和 ARC 已选择结果，做一次 agentic shadow 对比评估。"
                    "只能评估和提出替代建议，不能要求直接写库、投递、更新 memory 或覆盖 ARC 结果。"
                    "必须遵守 context.shadow_config.delegation_policy；如果 bounded_delegation_allowed=false，"
                    "只能模拟子角色分析，不能声称已执行 native delegation。"
                    "按最多 2 个子角色思路输出结构化 trace，例如 profile_history_reviewer 和 source_quality_reviewer。"
                    "重点比较 baseline selected_recommendations 与 shadow_recommendations：画像贴合、novelty、"
                    "start path、source validity、history fatigue、hard exclusion 风险、成本/延迟风险。"
                    '输出格式严格为 {"subagents_used":0,"roles":[...],"trace_mode":"simulated_trace|native_delegation",'
                    '"baseline_assessment":{...},"shadow_recommendations":[...],"comparison":{...},'
                    '"warnings":[],"confidence":0.0}。'
                ),
                "context": {
                    "profile_context": _bounded_text(profile_context, INTENT_PROFILE_CONTEXT_MAX_CHARS),
                    "recommendation_history_context": recommendation_history_context,
                    "themes": themes,
                    "recommendation_plan": recommendation_plan or {},
                    "generated_candidates": generated_candidates[:12],
                    "selected_recommendations": selected_recommendations[:6],
                    "shadow_config": shadow_config,
                    "local_session": self._local_session_context(),
                },
                "output_contract": {
                    "subagents_used": "integer",
                    "roles": ["string"],
                    "trace_mode": "simulated_trace|native_delegation",
                    "baseline_assessment": {
                        "profile_fit": "number 0..1",
                        "novelty": "number 0..1",
                        "start_path_quality": "number 0..1",
                        "source_validity": "number 0..1",
                        "risks": ["string"],
                    },
                    "shadow_recommendations": [
                        {
                            "title": "string",
                            "author": "string",
                            "slot_type": "profile_fit|exploration",
                            "theme": "string",
                            "reason": "string",
                            "source_url": "string",
                            "replace_baseline_title": "string",
                        }
                    ],
                    "comparison": {
                        "baseline_strengths": ["string"],
                        "shadow_strengths": ["string"],
                        "tradeoffs": ["string"],
                        "recommended_action": "observe_only|consider_later|needs_more_evidence",
                    },
                    "warnings": ["string"],
                    "confidence": "number 0..1",
                },
                "constraints": _constraints(),
            }
        )
        shadow = normalize_agentic_shadow(response)
        self._remember_local_turn(
            "reading.recommend.agentic_shadow_v1",
            {
                "theme_count": len(themes),
                "generated_candidates": len(generated_candidates),
                "selected_recommendations": len(selected_recommendations),
            },
            {
                "subagents_used": shadow.get("subagents_used", 0),
                "roles": shadow.get("roles", []),
                "confidence": shadow.get("confidence", 0.0),
            },
        )
        return shadow

    def _theme_intents_for_context(self, themes: list[str]) -> list[dict[str, str]]:
        by_theme = {intent.theme: intent for intent in self._last_theme_intents}
        intents = []
        for index, theme in enumerate(themes[:3]):
            intent = by_theme.get(theme)
            if intent is None:
                slot = "exploration" if index == 2 else "profile_fit"
                intent = ThemeIntent(theme=str(theme)[:80], slot=slot, reason="Inferred from theme order for backward compatibility.")
            intents.append(intent.as_dict())
        return intents

    def _call(self, payload: dict[str, Any]) -> dict[str, Any]:
        argv = shlex.split(self.command)
        if not argv:
            raise DailyAgentAdapterError("Hermes daily command is empty")
        try:
            completed = self.runner(
                argv,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise DailyAgentAdapterError("Hermes daily command not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise DailyAgentAdapterError("Hermes daily command timed out") from exc

        if completed.returncode != 0:
            stderr_tail = (completed.stderr or "").strip().splitlines()[-1:]
            detail = stderr_tail[0] if stderr_tail else f"exit status {completed.returncode}"
            raise DailyAgentAdapterError(f"Hermes daily command failed: {detail}")
        try:
            response = json.loads(completed.stdout or "")
        except json.JSONDecodeError as exc:
            raise DailyAgentAdapterError("Hermes daily command returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise DailyAgentAdapterError("Hermes daily command returned non-object JSON")
        return response

    def _local_session_context(self) -> dict[str, Any]:
        if self._local_session is None:
            return {
                "enabled": False,
                "reason": "no active ARC run-local session",
            }
        return {
            "enabled": True,
            "session_id": self._local_session["session_id"],
            "scope": self._local_session["scope"],
            "persistence": self._local_session["persistence"],
            "hermes_internal_thread": self._local_session["hermes_internal_thread"],
            "previous_turns": list(self._local_session.get("turns", []))[-4:],
        }

    def _remember_local_turn(self, route: str, request_summary: dict[str, Any], response_summary: dict[str, Any]) -> None:
        if self._local_session is None:
            return
        turns = self._local_session.setdefault("turns", [])
        if isinstance(turns, list):
            turns.append(
                {
                    "route": route,
                    "request_summary": request_summary,
                    "response_summary": response_summary,
                }
            )
            del turns[:-4]


def _constraints() -> dict[str, bool]:
    return {
        "do_not_modify_sqlite": True,
        "do_not_modify_files": True,
        "do_not_modify_memories": True,
        "do_not_send_messages": True,
        "do_not_modify_network_channels": True,
        "do_not_apply_patches": True,
        "business_orchestrator_writes_outputs": True,
    }


def daily_recommendation_runtime_capabilities(
    agent: DailyRecommendationAgentAdapter | None,
) -> dict[str, Any]:
    if agent is None:
        return {
            "schema_version": DAILY_AGENT_RUNTIME_CAPABILITY_SCHEMA_VERSION,
            "provider": "legacy-local",
            "runtime": "legacy-local",
            "supports_native_thread": False,
            "supports_delegation": False,
            "supports_memory": False,
            "supports_file": False,
            "supports_terminal": False,
            "supports_web": False,
            "supports_session_search": False,
            "side_effects_allowed": False,
        }

    provider = str(getattr(agent, "name", agent.__class__.__name__) or agent.__class__.__name__)
    capabilities = getattr(agent, "runtime_capabilities", None)
    if callable(capabilities):
        try:
            raw = capabilities()
        except Exception:
            logger.exception("Daily recommendation agent capability inspection failed")
            raw = {}
        if isinstance(raw, dict):
            return _normalize_runtime_capabilities(raw, provider)

    return {
        "schema_version": DAILY_AGENT_RUNTIME_CAPABILITY_SCHEMA_VERSION,
        "provider": provider,
        "runtime": "custom-adapter",
        "supports_native_thread": False,
        "supports_delegation": False,
        "supports_memory": False,
        "supports_file": False,
        "supports_terminal": False,
        "supports_web": False,
        "supports_session_search": False,
        "side_effects_allowed": False,
    }


def _normalize_runtime_capabilities(raw: dict[str, Any], provider: str) -> dict[str, Any]:
    bool_fields = (
        "supports_native_thread",
        "supports_delegation",
        "supports_memory",
        "supports_file",
        "supports_terminal",
        "supports_web",
        "supports_session_search",
        "side_effects_allowed",
    )
    normalized: dict[str, Any] = {
        "schema_version": DAILY_AGENT_RUNTIME_CAPABILITY_SCHEMA_VERSION,
        "provider": str(raw.get("provider") or provider)[:120],
        "runtime": str(raw.get("runtime") or "custom-adapter")[:120],
    }
    for field in bool_fields:
        normalized[field] = bool(raw.get(field, False))
    if "notes" in raw:
        normalized["notes"] = str(raw.get("notes") or "")[:500]
    return normalized


def normalize_theme_intents(raw_themes: Any) -> list[ThemeIntent]:
    if not isinstance(raw_themes, list):
        return []

    intents: list[ThemeIntent] = []
    for index, raw in enumerate(raw_themes):
        fallback_slot = "exploration" if index == 2 else "profile_fit"
        if isinstance(raw, dict):
            theme = str(raw.get("theme") or raw.get("name") or raw.get("title") or "").strip()
            slot = _normalize_theme_slot(raw.get("slot") or raw.get("slot_type"), fallback_slot)
            reason = str(raw.get("reason") or raw.get("rationale") or raw.get("profile_mapping") or "").strip()
        else:
            theme = str(raw).strip()
            slot = fallback_slot
            reason = "Legacy themes_v1 string; slot inferred from position."
        if not theme:
            continue
        intents.append(
            ThemeIntent(
                theme=theme[:80],
                slot=slot,
                reason=reason[:240] or "No explicit reason returned.",
            )
        )
        if len(intents) >= 3:
            break
    return intents


def normalize_recommendation_review(raw_review: Any) -> dict[str, Any]:
    if not isinstance(raw_review, dict):
        return {
            "schema_version": RECOMMENDATION_REVIEW_SCHEMA_VERSION,
            "verdict": "warn",
            "candidate_reviews": [],
            "global_warnings": ["Hermes review returned non-object JSON."],
            "revision_instructions": [],
            "confidence": 0.0,
        }

    verdict = str(raw_review.get("verdict") or raw_review.get("overall_verdict") or "warn").strip().lower()
    if verdict not in {"accept", "warn", "reject"}:
        verdict = "warn"
    candidate_reviews = raw_review.get("candidate_reviews", [])
    if not isinstance(candidate_reviews, list):
        candidate_reviews = []
    global_warnings = raw_review.get("global_warnings", raw_review.get("warnings", []))
    if not isinstance(global_warnings, list):
        global_warnings = [str(global_warnings)]
    revision_instructions = raw_review.get("revision_instructions", raw_review.get("suggested_actions", []))
    if not isinstance(revision_instructions, list):
        revision_instructions = [str(revision_instructions)]
    return {
        "schema_version": RECOMMENDATION_REVIEW_SCHEMA_VERSION,
        "verdict": verdict,
        "candidate_reviews": [item for item in candidate_reviews if isinstance(item, dict)][:20],
        "global_warnings": [str(item)[:500] for item in global_warnings if str(item).strip()][:20],
        "revision_instructions": [str(item)[:500] for item in revision_instructions if str(item).strip()][:20],
        "confidence": _float_score(raw_review.get("confidence"), 0.0),
    }


def normalize_recommendation_plan(raw_plan: Any) -> dict[str, Any]:
    if not isinstance(raw_plan, dict):
        return {
            "schema_version": RECOMMENDATION_PLAN_SCHEMA_VERSION,
            "slots": [],
            "global_risk_controls": ["Hermes plan returned non-object JSON."],
            "plan_summary": "",
            "confidence": 0.0,
        }

    raw_slots = raw_plan.get("slots")
    if not isinstance(raw_slots, list):
        raw_slots = []
    slots = []
    for index, raw_slot in enumerate(raw_slots):
        if not isinstance(raw_slot, dict):
            continue
        fallback_slot = "exploration" if index == 2 else "profile_fit"
        theme = str(raw_slot.get("theme") or raw_slot.get("name") or raw_slot.get("title") or "").strip()
        if not theme:
            continue
        slots.append(
            {
                "slot_type": _normalize_theme_slot(raw_slot.get("slot_type") or raw_slot.get("slot"), fallback_slot),
                "theme": theme[:120],
                "search_queries": _bounded_string_list(raw_slot.get("search_queries") or raw_slot.get("queries"), 5, 160),
                "candidate_criteria": _bounded_string_list(raw_slot.get("candidate_criteria") or raw_slot.get("criteria"), 8, 240),
                "risk_controls": _bounded_string_list(raw_slot.get("risk_controls"), 8, 240),
                "reason": str(raw_slot.get("reason") or raw_slot.get("rationale") or "")[:500],
            }
        )
        if len(slots) >= 3:
            break
    return {
        "schema_version": RECOMMENDATION_PLAN_SCHEMA_VERSION,
        "slots": slots,
        "global_risk_controls": _bounded_string_list(raw_plan.get("global_risk_controls"), 10, 240),
        "plan_summary": str(raw_plan.get("plan_summary") or raw_plan.get("summary") or "")[:800],
        "confidence": _float_score(raw_plan.get("confidence"), 0.0),
    }


def normalize_agentic_shadow(raw_shadow: Any) -> dict[str, Any]:
    if not isinstance(raw_shadow, dict):
        return {
            "schema_version": AGENTIC_SHADOW_SCHEMA_VERSION,
            "subagents_used": 0,
            "roles": [],
            "trace_mode": "simulated_trace",
            "baseline_assessment": {},
            "shadow_recommendations": [],
            "comparison": {},
            "warnings": ["Hermes agentic shadow returned non-object JSON."],
            "confidence": 0.0,
        }

    trace_mode = str(raw_shadow.get("trace_mode") or "simulated_trace").strip()
    if trace_mode not in {"simulated_trace", "native_delegation"}:
        trace_mode = "simulated_trace"
    comparison = raw_shadow.get("comparison")
    if not isinstance(comparison, dict):
        comparison = {}
    baseline_assessment = raw_shadow.get("baseline_assessment")
    if not isinstance(baseline_assessment, dict):
        baseline_assessment = {}
    raw_recommendations = raw_shadow.get("shadow_recommendations")
    if not isinstance(raw_recommendations, list):
        raw_recommendations = []
    return {
        "schema_version": AGENTIC_SHADOW_SCHEMA_VERSION,
        "subagents_used": min(max(_int_value(raw_shadow.get("subagents_used"), 0), 0), 8),
        "roles": _bounded_string_list(raw_shadow.get("roles"), 8, 120),
        "trace_mode": trace_mode,
        "baseline_assessment": baseline_assessment,
        "shadow_recommendations": [item for item in raw_recommendations if isinstance(item, dict)][:12],
        "comparison": comparison,
        "warnings": _bounded_string_list(raw_shadow.get("warnings"), 20, 500),
        "confidence": _float_score(raw_shadow.get("confidence"), 0.0),
    }


def _normalize_theme_slot(raw_slot: Any, fallback: str) -> str:
    slot = str(raw_slot or "").strip().lower()
    if slot in {"profile_fit", "profile-fit", "fit", "profile"}:
        return "profile_fit"
    if slot in {"exploration", "explore", "exploratory"}:
        return "exploration"
    return fallback if fallback in {"profile_fit", "exploration"} else "profile_fit"


def _bounded_string_list(raw: Any, limit: int, max_chars: int) -> list[str]:
    if isinstance(raw, list):
        values = raw
    elif raw is None:
        values = []
    else:
        values = [raw]
    return [str(item).strip()[:max_chars] for item in values if str(item).strip()][:limit]


def build_effective_profile_summary(profile_context: str) -> str:
    selected = []
    for line in profile_context.splitlines():
        stripped = " ".join(line.strip().split())
        if not stripped:
            continue
        if _is_summary_signal(stripped):
            selected.append(stripped[:220])
        if len(selected) >= EFFECTIVE_PROFILE_SUMMARY_MAX_LINES:
            break

    if not selected:
        selected = ["暂无高置信画像摘要；按 Priority 1-5 保守使用原始画像上下文。"]

    lines = [
        "EffectiveProfileSummary:",
        "- Priority order: Hermes native USER memory > explicit ARC feedback > ARC inferred profile > ARC applied reflection memory > single-run weak signals.",
        "- Stable and relevant signals:",
        *[f"  - {line}" for line in selected],
        "- Book-selection steering:",
        "  - Favor concrete book themes over abstract interest labels.",
        "  - Keep literature/classics and classic science fiction visible when supported by profile evidence.",
        "  - Treat engineering, business, productivity, and tool-book topics as capped unless fresh positive feedback exists.",
    ]
    return "\n".join(lines)


def _is_summary_signal(line: str) -> bool:
    markers = (
        "Hermes native USER.md",
        "[arc-reading-profile]",
        "Reading Preferences",
        "Long-term Interests",
        "Aversion Patterns",
        "稳定",
        "明确反馈",
        "经典",
        "名著",
        "文学",
        "科幻",
        "高口碑",
        "偏好",
        "避免",
        "降频",
        "反感",
        "不感兴趣",
    )
    return any(marker in line for marker in markers)


def _bounded_text(text: str, max_chars: int) -> str:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "\n...[truncated for reading.recommend.intent]"


def _float_score(raw: Any, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def _int_value(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def build_daily_recommendation_agent(
    provider: str,
    hermes_agent_command: str,
    hermes_agent_timeout_seconds: float,
) -> DailyRecommendationAgentAdapter | None:
    normalized = provider.strip().lower()
    if normalized in {"", "custom", "legacy", "direct"}:
        return None
    if normalized in {"hermes-agent", "hermes_agent", "hermes"}:
        return HermesDailyRecommendationAdapter(
            command=hermes_agent_command,
            timeout_seconds=hermes_agent_timeout_seconds,
        )
    raise ValueError(f"Unsupported DAILY_RECOMMENDATION_PROVIDER: {provider}")
