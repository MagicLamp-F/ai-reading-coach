from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    channel: str
    lark_webhook_url: str
    lark_webhook_secret: str
    public_base_url: str
    feedback_secret: str
    telegram_bot_token: str
    telegram_chat_id: str
    model_provider: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    tavily_api_key: str
    database_path: Path
    daily_push_time: str
    timezone: ZoneInfo
    http_timeout_seconds: float
    max_daily_search_calls: int
    max_daily_model_calls: int
    daily_recommendation_provider: str
    hermes_reflection_provider: str
    hermes_agent_command: str
    hermes_agent_timeout_seconds: float
    hermes_reflection_auto_apply: bool
    daily_reflection_enabled: bool
    daily_reflection_days: int
    daily_reading_packs_enabled: bool
    reading_pack_provider: str
    reading_pack_library_dir: Path
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            channel=os.getenv("CHANNEL", "lark").strip().lower(),
            lark_webhook_url=os.getenv("LARK_WEBHOOK_URL", ""),
            lark_webhook_secret=os.getenv("LARK_WEBHOOK_SECRET", ""),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
            feedback_secret=os.getenv("FEEDBACK_SECRET", ""),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            model_provider=os.getenv("MODEL_PROVIDER", "openai"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            database_path=_database_path(os.getenv("DATABASE_URL", "sqlite:///data/reading_coach.db")),
            daily_push_time=os.getenv("DAILY_PUSH_TIME", "08:00"),
            timezone=ZoneInfo(os.getenv("TIMEZONE", "Asia/Shanghai")),
            http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "20")),
            max_daily_search_calls=int(os.getenv("MAX_DAILY_SEARCH_CALLS", "6")),
            max_daily_model_calls=int(os.getenv("MAX_DAILY_MODEL_CALLS", "4")),
            daily_recommendation_provider=os.getenv("DAILY_RECOMMENDATION_PROVIDER", "custom").strip().lower(),
            hermes_reflection_provider=os.getenv("HERMES_REFLECTION_PROVIDER", "custom").strip().lower(),
            hermes_agent_command=os.getenv(
                "HERMES_AGENT_COMMAND",
                "/home/ubuntu/projects/hermes-agent/bin/reflect-json",
            ),
            hermes_agent_timeout_seconds=float(os.getenv("HERMES_AGENT_TIMEOUT_SECONDS", "60")),
            hermes_reflection_auto_apply=_env_bool("HERMES_REFLECTION_AUTO_APPLY", False),
            daily_reflection_enabled=_env_bool("DAILY_REFLECTION_ENABLED", False),
            daily_reflection_days=int(os.getenv("DAILY_REFLECTION_DAYS", "1")),
            daily_reading_packs_enabled=_env_bool("DAILY_READING_PACKS_ENABLED", True),
            reading_pack_provider=os.getenv("READING_PACK_PROVIDER", "custom").strip().lower(),
            reading_pack_library_dir=Path(os.getenv("READING_PACK_LIBRARY_DIR", "library")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


def _database_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Only sqlite:/// DATABASE_URL is supported in the MVP")
    raw_path = database_url[len(prefix) :]
    return Path(raw_path)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
