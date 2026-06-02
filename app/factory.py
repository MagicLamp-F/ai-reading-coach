from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.daily_agent_adapter import DailyRecommendationAgentAdapter, build_daily_recommendation_agent
from app.db import connect, init_db
from app.http_client import HttpClient
from app.lark import LarkRobotClient
from app.llm import OpenAIChatClient
from app.reflection_adapter import ReflectionAgentAdapter, build_reflection_adapter
from app.reading_pack import HermesReadingPackAdapter, build_reading_pack_agent
from app.repository import Repository
from app.search import TavilySearch
from app.source_collector import BookSourceCollector
from app.telegram import TelegramClient
from app.workflow import ReadingCoachWorkflow


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    repo: Repository
    workflow: ReadingCoachWorkflow
    lark: LarkRobotClient
    telegram: TelegramClient
    reflection_adapter: ReflectionAgentAdapter
    daily_recommendation_agent: DailyRecommendationAgentAdapter | None
    reading_pack_agent: HermesReadingPackAdapter | None
    source_collector: BookSourceCollector


def build_context(settings: Settings) -> AppContext:
    conn = connect(settings.database_path)
    init_db(conn)
    repo = Repository(conn)
    http = HttpClient(timeout_seconds=settings.http_timeout_seconds)
    search = TavilySearch(settings.tavily_api_key, http)
    llm = OpenAIChatClient(settings.openai_api_key, settings.openai_model, settings.openai_base_url, http)
    lark = LarkRobotClient(
        settings.lark_webhook_url,
        settings.lark_webhook_secret,
        http,
        max_send_attempts=settings.lark_max_send_attempts,
        retry_base_seconds=settings.lark_retry_base_seconds,
        rate_limit_cooldown_seconds=settings.lark_rate_limit_cooldown_seconds,
    )
    telegram = TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id, http)
    source_http = HttpClient(
        timeout_seconds=settings.source_fetch_timeout_seconds,
        retries=settings.source_fetch_retries,
    )
    source_collector = BookSourceCollector(
        repo,
        source_http,
        search=search,
        search_enabled=settings.source_search_enabled,
        max_search_results=settings.source_search_max_results,
        search_depth=settings.source_search_depth,
        search_queries_per_book=settings.source_search_queries_per_book,
        include_raw_content=settings.source_search_include_raw_content,
    )
    reflection_adapter = build_reflection_adapter(
        provider=settings.hermes_reflection_provider,
        llm=llm,
        hermes_agent_command=settings.hermes_agent_command,
        hermes_agent_timeout_seconds=settings.hermes_agent_timeout_seconds,
    )
    daily_recommendation_agent = build_daily_recommendation_agent(
        provider=settings.daily_recommendation_provider,
        hermes_agent_command=settings.hermes_agent_command,
        hermes_agent_timeout_seconds=settings.hermes_agent_timeout_seconds,
    )
    reading_pack_agent = build_reading_pack_agent(
        provider=settings.reading_pack_provider,
        hermes_agent_command=settings.hermes_agent_command,
        hermes_agent_timeout_seconds=settings.hermes_agent_timeout_seconds,
    )
    workflow = ReadingCoachWorkflow(
        repo=repo,
        search=search,
        llm=llm,
        lark=lark,
        telegram=telegram,
        channel=settings.channel,
        public_base_url=settings.public_base_url,
        feedback_secret=settings.feedback_secret,
        max_search_calls=settings.max_daily_search_calls,
        max_model_calls=settings.max_daily_model_calls,
        daily_recommendation_count=settings.daily_recommendation_count,
        reading_packs_enabled=settings.daily_reading_packs_enabled,
        reading_pack_library_dir=settings.reading_pack_library_dir,
        daily_recommendation_agent=daily_recommendation_agent,
        reading_pack_agent=reading_pack_agent,
        source_collector=source_collector,
        source_aware_recommendations=settings.source_aware_recommendations,
        source_aware_strict_mode=settings.source_aware_strict_mode,
        source_aware_candidate_count=settings.source_aware_candidate_count,
        source_min_coverage_score=settings.source_min_coverage_score,
        source_aware_allow_limited_fill=settings.source_aware_allow_limited_fill,
    )
    return AppContext(
        settings=settings,
        repo=repo,
        workflow=workflow,
        lark=lark,
        telegram=telegram,
        reflection_adapter=reflection_adapter,
        daily_recommendation_agent=daily_recommendation_agent,
        reading_pack_agent=reading_pack_agent,
        source_collector=source_collector,
    )
