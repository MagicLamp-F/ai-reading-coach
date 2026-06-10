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
    lark_max_send_attempts: int
    lark_retry_base_seconds: float
    lark_rate_limit_cooldown_seconds: float
    public_base_url: str
    feedback_secret: str
    telegram_bot_token: str
    telegram_chat_id: str
    model_provider: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    tavily_api_key: str
    tavily_api_key_file: Path
    database_path: Path
    daily_push_time: str
    timezone: ZoneInfo
    http_timeout_seconds: float
    max_daily_search_calls: int
    max_daily_model_calls: int
    daily_recommendation_count: int
    daily_recommendation_provider: str
    hermes_reflection_provider: str
    hermes_native_profile_path: Path
    hermes_soul_path: Path
    hermes_native_profile_max_chars: int
    hermes_native_user_memory_path: Path | None
    hermes_native_user_memory_char_limit: int
    hermes_agent_command: str
    hermes_agent_timeout_seconds: float
    hermes_reflection_auto_apply: bool
    daily_reflection_enabled: bool
    daily_reflection_days: int
    daily_reading_packs_enabled: bool
    reading_pack_provider: str
    reading_pack_library_dir: Path
    source_search_enabled: bool
    source_search_max_results: int
    source_search_depth: str
    source_search_queries_per_book: int
    source_search_include_raw_content: bool
    source_fetch_timeout_seconds: float
    source_fetch_retries: int
    source_aware_recommendations: bool
    source_aware_strict_mode: bool
    source_aware_candidate_count: int
    source_min_coverage_score: float
    source_aware_allow_limited_fill: bool
    admin_username: str
    admin_password: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            channel=os.getenv("CHANNEL", "lark").strip().lower(),
            lark_webhook_url=os.getenv("LARK_WEBHOOK_URL", ""),
            lark_webhook_secret=os.getenv("LARK_WEBHOOK_SECRET", ""),
            lark_max_send_attempts=int(os.getenv("LARK_MAX_SEND_ATTEMPTS", "3")),
            lark_retry_base_seconds=float(os.getenv("LARK_RETRY_BASE_SECONDS", "2")),
            lark_rate_limit_cooldown_seconds=float(os.getenv("LARK_RATE_LIMIT_COOLDOWN_SECONDS", "90")),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
            feedback_secret=os.getenv("FEEDBACK_SECRET", ""),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            model_provider=os.getenv("MODEL_PROVIDER", "openai"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            tavily_api_key=_secret_from_env_or_file(
                "TAVILY_API_KEY",
                os.getenv("TAVILY_API_KEY_FILE", "/home/ubuntu/.config/tavily/api_key"),
            ),
            tavily_api_key_file=Path(os.getenv("TAVILY_API_KEY_FILE", "/home/ubuntu/.config/tavily/api_key")),
            database_path=_database_path(os.getenv("DATABASE_URL", "sqlite:///data/reading_coach.db")),
            daily_push_time=os.getenv("DAILY_PUSH_TIME", "08:00"),
            timezone=ZoneInfo(os.getenv("TIMEZONE", "Asia/Shanghai")),
            http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "20")),
            max_daily_search_calls=int(os.getenv("MAX_DAILY_SEARCH_CALLS", "6")),
            max_daily_model_calls=int(os.getenv("MAX_DAILY_MODEL_CALLS", "4")),
            daily_recommendation_count=int(os.getenv("DAILY_RECOMMENDATION_COUNT", "3")),
            daily_recommendation_provider=os.getenv("DAILY_RECOMMENDATION_PROVIDER", "hermes-agent").strip().lower(),
            hermes_reflection_provider=os.getenv("HERMES_REFLECTION_PROVIDER", "hermes-agent").strip().lower(),
            hermes_native_profile_path=Path(os.getenv("HERMES_NATIVE_PROFILE_PATH", "memory/HERMES_NATIVE_PROFILE.md")),
            hermes_soul_path=Path(os.getenv("HERMES_SOUL_PATH", "/home/ubuntu/.hermes/SOUL.md")),
            hermes_native_profile_max_chars=int(os.getenv("HERMES_NATIVE_PROFILE_MAX_CHARS", "6000")),
            hermes_native_user_memory_path=_optional_path(
                os.getenv("HERMES_NATIVE_USER_MEMORY_PATH", "/home/ubuntu/.hermes/memories/USER.md")
            ),
            hermes_native_user_memory_char_limit=int(os.getenv("HERMES_NATIVE_USER_MEMORY_CHAR_LIMIT", "1375")),
            hermes_agent_command=os.getenv(
                "HERMES_AGENT_COMMAND",
                "/home/ubuntu/projects/hermes-agent/bin/reflect-json",
            ),
            hermes_agent_timeout_seconds=float(os.getenv("HERMES_AGENT_TIMEOUT_SECONDS", "60")),
            hermes_reflection_auto_apply=_env_bool("HERMES_REFLECTION_AUTO_APPLY", False),
            daily_reflection_enabled=_env_bool("DAILY_REFLECTION_ENABLED", False),
            daily_reflection_days=int(os.getenv("DAILY_REFLECTION_DAYS", "1")),
            daily_reading_packs_enabled=_env_bool("DAILY_READING_PACKS_ENABLED", True),
            reading_pack_provider=os.getenv("READING_PACK_PROVIDER", "hermes-agent").strip().lower(),
            reading_pack_library_dir=Path(os.getenv("READING_PACK_LIBRARY_DIR", "library")),
            source_search_enabled=_env_bool("SOURCE_SEARCH_ENABLED", True),
            source_search_max_results=int(os.getenv("SOURCE_SEARCH_MAX_RESULTS", "5")),
            source_search_depth=os.getenv("SOURCE_SEARCH_DEPTH", "advanced").strip().lower(),
            source_search_queries_per_book=int(os.getenv("SOURCE_SEARCH_QUERIES_PER_BOOK", "6")),
            source_search_include_raw_content=_env_bool("SOURCE_SEARCH_INCLUDE_RAW_CONTENT", True),
            source_fetch_timeout_seconds=float(os.getenv("SOURCE_FETCH_TIMEOUT_SECONDS", "6")),
            source_fetch_retries=int(os.getenv("SOURCE_FETCH_RETRIES", "0")),
            source_aware_recommendations=_env_bool("SOURCE_AWARE_RECOMMENDATIONS", True),
            source_aware_strict_mode=_env_bool("SOURCE_AWARE_STRICT_MODE", True),
            source_aware_candidate_count=int(os.getenv("SOURCE_AWARE_CANDIDATE_COUNT", "6")),
            source_min_coverage_score=float(os.getenv("SOURCE_MIN_COVERAGE_SCORE", "0.5")),
            source_aware_allow_limited_fill=_env_bool("SOURCE_AWARE_ALLOW_LIMITED_FILL", False),
            admin_username=os.getenv("ARC_ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("ARC_ADMIN_PASSWORD", "123456"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


def _database_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Only sqlite:/// DATABASE_URL is supported in the MVP")
    raw_path = database_url[len(prefix) :]
    return Path(raw_path)


def _optional_path(value: str) -> Path | None:
    stripped = value.strip()
    if not stripped:
        return None
    return Path(stripped)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _secret_from_env_or_file(env_name: str, file_path: str) -> str:
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    path = Path(file_path).expanduser()
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""
