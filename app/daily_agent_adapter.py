from __future__ import annotations

import json
import logging
import shlex
import subprocess
from typing import Any, Protocol

from app.search import SearchResult

logger = logging.getLogger(__name__)


class DailyAgentAdapterError(RuntimeError):
    pass


class DailyRecommendationAgentAdapter(Protocol):
    name: str

    def generate_themes(self, profile_context: str) -> list[str]:
        ...

    def generate_recommendations(
        self,
        profile_context: str,
        themes: list[str],
        search_results: list[SearchResult],
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

    def generate_themes(self, profile_context: str) -> list[str]:
        response = self._call(
            {
                "route": "reading.recommend.intent",
                "domain": "reading",
                "tool_policy": "none",
                "output_schema": "themes_v1",
                "format": "json",
                "system_prompt": "你是读书推荐系统的 Hermes 画像决策层。只输出 JSON。",
                "user_prompt": (
                    "根据用户画像上下文生成今日推荐主题。要求 2 个贴合画像主题，1 个探索型主题。"
                    '输出格式严格为 {"themes":["主题1","主题2","主题3"]}。'
                ),
                "context": {"profile_context": profile_context},
                "output_contract": {"themes": ["string"]},
                "constraints": _constraints(),
            }
        )
        themes = response.get("themes")
        if not isinstance(themes, list) or not themes:
            raise DailyAgentAdapterError("Hermes returned no themes")
        return [str(theme)[:80] for theme in themes if str(theme).strip()][:3]

    def generate_recommendations(
        self,
        profile_context: str,
        themes: list[str],
        search_results: list[SearchResult],
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
                    "基于用户画像上下文、今日主题和搜索结果，筛选并推荐 3 本书。"
                    "每本书必须包含 title, author, source_url, slot_type, theme, system_hypothesis, "
                    "profile_dimensions, recommendation_reason, profile_mapping, expected_benefit, risk, reading_suggestion。"
                    "slot_type 只能是 profile_fit 或 exploration。"
                    '输出格式严格为 {"books":[...]}。'
                ),
                "context": {
                    "profile_context": profile_context,
                    "themes": themes,
                    "search_results": search_context,
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
        return [book for book in books if isinstance(book, dict)][:3]

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
