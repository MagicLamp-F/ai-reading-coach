from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.db import connect, init_db
from app.http_client import HttpClient
from app.lark import LarkRobotClient
from app.llm import OpenAIChatClient
from app.reflection_adapter import ReflectionAgentAdapter, build_reflection_adapter
from app.repository import Repository
from app.search import TavilySearch
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


def build_context(settings: Settings) -> AppContext:
    conn = connect(settings.database_path)
    init_db(conn)
    repo = Repository(conn)
    http = HttpClient(timeout_seconds=settings.http_timeout_seconds)
    search = TavilySearch(settings.tavily_api_key, http)
    llm = OpenAIChatClient(settings.openai_api_key, settings.openai_model, settings.openai_base_url, http)
    lark = LarkRobotClient(settings.lark_webhook_url, settings.lark_webhook_secret, http)
    telegram = TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id, http)
    reflection_adapter = build_reflection_adapter(
        provider=settings.hermes_reflection_provider,
        llm=llm,
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
    )
    return AppContext(
        settings=settings,
        repo=repo,
        workflow=workflow,
        lark=lark,
        telegram=telegram,
        reflection_adapter=reflection_adapter,
    )
