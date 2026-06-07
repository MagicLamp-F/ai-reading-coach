from __future__ import annotations

import json
import logging
import shlex
import subprocess
from datetime import datetime, timezone
from typing import Any, Protocol

from app.search import SearchResult

logger = logging.getLogger(__name__)


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

    def start_local_session(self, run_id: int, purpose: str = "run_daily") -> None:
        self._local_session = {
            "session_id": f"arc-{purpose}-{run_id}",
            "scope": purpose,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "persistence": "bounded_to_current_arc_run",
            "hermes_internal_thread": "not_supported_by_current_reflect_json_wrapper",
            "turns": [],
        }

    def end_local_session(self) -> None:
        self._local_session = None

    def generate_themes(self, profile_context: str, recommendation_history_context: str = "") -> list[str]:
        response = self._call(
            {
                "route": "reading.recommend.intent",
                "domain": "reading",
                "tool_policy": "none",
                "output_schema": "themes_v1",
                "format": "json",
                "system_prompt": "你是读书推荐系统的 Hermes 画像决策层。只输出 JSON。",
                "user_prompt": (
                    "根据用户画像上下文和推荐历史生成今日推荐主题。要求 2 个贴合画像主题，1 个探索型主题。"
                    "如果画像显示用户偏好经典名著、文学、科幻或高口碑作品，主题必须明显覆盖这些方向，"
                    "避免重复最近高频主题，除非推荐历史显示用户明确正反馈。"
                    "不要只生成工程技术、商业或工具书主题。"
                    '输出格式严格为 {"themes":["主题1","主题2","主题3"]}。'
                ),
                "context": {
                    "profile_context": profile_context,
                    "recommendation_history_context": recommendation_history_context,
                    "local_session": self._local_session_context(),
                },
                "output_contract": {"themes": ["string"]},
                "constraints": _constraints(),
            }
        )
        themes = response.get("themes")
        if not isinstance(themes, list) or not themes:
            raise DailyAgentAdapterError("Hermes returned no themes")
        normalized = [str(theme)[:80] for theme in themes if str(theme).strip()][:3]
        self._remember_local_turn(
            "reading.recommend.intent",
            {"profile_context_chars": len(profile_context), "history_context_chars": len(recommendation_history_context)},
            {"themes": normalized},
        )
        return normalized

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
        "do_not_send_messages": True,
        "do_not_apply_patches": True,
        "business_orchestrator_writes_outputs": True,
    }


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
