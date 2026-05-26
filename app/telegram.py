from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from urllib.parse import quote

from app.http_client import HttpClient

logger = logging.getLogger(__name__)


FEEDBACK_LABELS = {
    "like": "喜欢",
    "neutral": "一般",
    "not_interested": "不感兴趣",
    "already_read": "已读",
    "go_deeper": "想深入",
}


@dataclass(frozen=True)
class FeedbackCallback:
    callback_query_id: str
    recommendation_id: int
    feedback_type: str
    user_text: str


class TelegramClient:
    def __init__(self, bot_token: str, chat_id: str, http: HttpClient):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.http = http

    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, reply_markup: dict | None = None) -> str | None:
        if not self.enabled():
            logger.info("Telegram disabled; message not sent: %s", text[:200])
            return None
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        response = self.http.post_json(self._url("sendMessage"), payload)
        if response.status >= 400 or not response.body.get("ok", False):
            logger.warning("Telegram send failed: status=%s body=%s", response.status, response.body)
            return None
        return str(response.body.get("result", {}).get("message_id", ""))

    def get_updates(self, offset: int | None = None, timeout_seconds: int = 20) -> list[dict]:
        if not self.bot_token:
            return []
        params = f"?timeout={timeout_seconds}"
        if offset is not None:
            params += f"&offset={offset}"
        response = self.http.get_json(self._url(f"getUpdates{params}"))
        if response.status >= 400 or not response.body.get("ok", False):
            logger.warning("Telegram getUpdates failed: status=%s body=%s", response.status, response.body)
            return []
        return list(response.body.get("result", []))

    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        if not self.bot_token:
            return
        self.http.post_json(
            self._url("answerCallbackQuery"),
            {"callback_query_id": callback_query_id, "text": text, "show_alert": False},
        )

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{quote(self.bot_token, safe=':')}/{method}"


def feedback_markup(recommendation_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": label, "callback_data": f"fb:{recommendation_id}:{feedback_type}"}
                for feedback_type, label in FEEDBACK_LABELS.items()
            ]
        ]
    }


def parse_feedback_updates(updates: list[dict]) -> tuple[int | None, list[FeedbackCallback]]:
    next_offset = None
    callbacks: list[FeedbackCallback] = []
    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            next_offset = max(next_offset or 0, update_id + 1)
        callback = update.get("callback_query")
        if not callback:
            continue
        data = str(callback.get("data", ""))
        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "fb":
            continue
        try:
            recommendation_id = int(parts[1])
        except ValueError:
            continue
        feedback_type = parts[2]
        if feedback_type not in FEEDBACK_LABELS:
            continue
        callbacks.append(
            FeedbackCallback(
                callback_query_id=str(callback.get("id", "")),
                recommendation_id=recommendation_id,
                feedback_type=feedback_type,
                user_text=str(callback.get("message", {}).get("text", "")),
            )
        )
    return next_offset, callbacks


def format_recommendation_message(index: int, total: int, draft) -> str:
    title = html.escape(draft.title)
    author = html.escape(draft.author or "未知作者")
    theme = html.escape(draft.theme)
    hypothesis = html.escape(draft.system_hypothesis)
    dimensions = html.escape("、".join(draft.profile_dimensions) if draft.profile_dimensions else "未标注")
    reason = html.escape(draft.recommendation_reason)
    mapping = html.escape(draft.profile_mapping)
    benefit = html.escape(draft.expected_benefit)
    risk = html.escape(draft.risk)
    suggestion = html.escape(draft.reading_suggestion)
    url = html.escape(draft.source_url)
    link_line = f"\n来源：{url}" if url else ""
    return (
        f"<b>今日推荐 {index}/{total}</b>\n"
        f"<b>{title}</b>\n"
        f"作者：{author}\n"
        f"主题：{theme}\n\n"
        f"系统假设：{hypothesis}\n"
        f"测试画像维度：{dimensions}\n"
        f"推荐理由：{reason}\n"
        f"对应画像：{mapping}\n"
        f"可能收益：{benefit}\n"
        f"不推荐风险：{risk}\n"
        f"建议读法：{suggestion}"
        f"{link_line}"
    )
