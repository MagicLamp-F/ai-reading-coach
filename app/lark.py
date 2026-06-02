from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

from app.feedback import FEEDBACK_LABELS
from app.http_client import HttpClient

logger = logging.getLogger(__name__)


def generate_lark_sign(timestamp: int | str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


@dataclass(frozen=True)
class LarkFeedbackLink:
    feedback_type: str
    url: str


class LarkRobotClient:
    def __init__(
        self,
        webhook_url: str,
        webhook_secret: str,
        http: HttpClient,
        max_send_attempts: int = 3,
        retry_base_seconds: float = 2.0,
        rate_limit_cooldown_seconds: float = 90.0,
        sleeper=time.sleep,
    ):
        self.webhook_url = webhook_url
        self.webhook_secret = webhook_secret
        self.http = http
        self.max_send_attempts = max(1, max_send_attempts)
        self.retry_base_seconds = retry_base_seconds
        self.rate_limit_cooldown_seconds = rate_limit_cooldown_seconds
        self.sleeper = sleeper
        self.last_send_error = ""

    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def send_text(self, text: str) -> str | None:
        payload = self._signed_payload({"msg_type": "text", "content": {"text": text}})
        return self._send(payload)

    def send_profile_test_summary(self, drafts: list) -> str | None:
        hypotheses = "\n".join(f"{index}. {draft.system_hypothesis}" for index, draft in enumerate(drafts, start=1))
        dimensions = _unique_dimensions(drafts)
        dimension_text = "、".join(dimensions) if dimensions else "未标注"
        payload = self._signed_payload(
            {
                "msg_type": "interactive",
                "card": {
                    "config": {"wide_screen_mode": True},
                    "header": {"title": {"tag": "plain_text", "content": "今日画像测试"}},
                    "elements": [
                        {"tag": "div", "text": {"tag": "lark_md", "content": f"**今天测试的 3 个 system_hypothesis**\n{hypotheses}"}},
                        {"tag": "div", "text": {"tag": "lark_md", "content": f"**涉及的 profile_dimensions**\n{dimension_text}"}},
                        {"tag": "hr"},
                        {"tag": "div", "text": {"tag": "lark_md", "content": "请通过每本书下方的反馈按钮，帮助系统验证这些假设是否贴合你当前的阅读需求。"}},
                    ],
                },
            }
        )
        return self._send(payload)

    def send_recommendation(
        self,
        index: int,
        total: int,
        draft,
        feedback_links: list[LarkFeedbackLink],
        reading_pack_preview=None,
    ) -> str | None:
        dimensions = "、".join(draft.profile_dimensions) if draft.profile_dimensions else "未标注"
        elements = [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**{draft.title}**\n作者：{draft.author or '未知作者'}\n主题：{draft.theme}"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**系统假设**：{draft.system_hypothesis}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**测试画像维度**：{dimensions}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**推荐理由**：{draft.recommendation_reason}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**可能收益**：{draft.expected_benefit}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**可能不适合的原因**：{draft.risk}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**建议读法**：{draft.reading_suggestion}"}},
        ]
        if reading_pack_preview is not None:
            elements.extend(_reading_pack_elements(reading_pack_preview))
        if draft.source_url:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"[来源链接]({draft.source_url})"}})
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": FEEDBACK_LABELS[link.feedback_type]},
                        "url": link.url,
                        "type": "default",
                    }
                    for link in feedback_links
                ],
            }
        )
        payload = self._signed_payload(
            {
                "msg_type": "interactive",
                "card": {
                    "config": {"wide_screen_mode": True},
                    "header": {"title": {"tag": "plain_text", "content": f"今日推荐 {index}/{total}"}},
                    "elements": elements,
                },
            }
        )
        return self._send(payload)

    def send_reading_pack_preview(self, reading_pack_preview) -> str | None:
        payload = self._signed_payload(
            {
                "msg_type": "interactive",
                "card": {
                    "config": {"wide_screen_mode": True},
                    "header": {"title": {"tag": "plain_text", "content": "深度读完包"}},
                    "elements": _reading_pack_elements(reading_pack_preview),
                },
            }
        )
        return self._send(payload)

    def _signed_payload(self, payload: dict) -> dict:
        if not self.webhook_secret:
            return payload
        timestamp = str(int(time.time()))
        return {**payload, "timestamp": timestamp, "sign": generate_lark_sign(timestamp, self.webhook_secret)}

    def _send(self, payload: dict) -> str | None:
        self.last_send_error = ""
        if not self.enabled():
            logger.info("Lark disabled; message not sent: msg_type=%s", payload.get("msg_type"))
            return None
        last_response = None
        last_error: Exception | None = None
        for attempt in range(1, self.max_send_attempts + 1):
            try:
                response = self.http.post_json(self.webhook_url, payload)
            except Exception as exc:
                last_error = exc
                self.last_send_error = f"exception={exc}"
                if attempt >= self.max_send_attempts:
                    break
                delay = self.retry_base_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "Lark send exception; retrying: attempt=%s error=%s delay=%s",
                    attempt,
                    exc,
                    delay,
                )
                self.sleeper(delay)
                continue
            last_response = response
            code = response.body.get("code", 0)
            if response.status < 400 and code in (0, None):
                self.last_send_error = ""
                return str(response.body.get("message_id") or response.body.get("data", {}).get("message_id") or "")
            self.last_send_error = f"status={response.status} code={code} msg={response.body.get('msg')}"
            if not _should_retry_lark_send(response.status, code) or attempt >= self.max_send_attempts:
                break
            delay = _lark_retry_delay(
                status=response.status,
                code=code,
                attempt=attempt,
                retry_base_seconds=self.retry_base_seconds,
                rate_limit_cooldown_seconds=self.rate_limit_cooldown_seconds,
            )
            logger.warning(
                "Lark send temporary failure; retrying: attempt=%s status=%s code=%s msg=%s delay=%s",
                attempt,
                response.status,
                code,
                response.body.get("msg"),
                delay,
            )
            self.sleeper(delay)

        if last_response is not None:
            logger.warning(
                "Lark send failed: status=%s code=%s msg=%s",
                last_response.status,
                last_response.body.get("code"),
                last_response.body.get("msg"),
            )
        elif last_error is not None:
            logger.warning("Lark send failed with exception: %s", last_error)
        return None


def _should_retry_lark_send(status: int, code) -> bool:
    if status == 429 or status >= 500:
        return True
    return str(code) in {"11232"}


def _lark_retry_delay(
    status: int,
    code,
    attempt: int,
    retry_base_seconds: float,
    rate_limit_cooldown_seconds: float,
) -> float:
    if str(code) == "11232":
        return max(0.0, rate_limit_cooldown_seconds)
    return max(0.0, retry_base_seconds) * (2 ** (attempt - 1))


def _unique_dimensions(drafts: list) -> list[str]:
    seen = set()
    dimensions = []
    for draft in drafts:
        for dimension in getattr(draft, "profile_dimensions", []) or []:
            dimension = str(dimension).strip()
            if dimension and dimension not in seen:
                seen.add(dimension)
                dimensions.append(dimension)
    return dimensions


def _reading_pack_elements(reading_pack_preview) -> list[dict]:
    core_points = getattr(reading_pack_preview, "core_points", ()) or ()
    core_text = "\n".join(f"- {point}" for point in core_points if str(point).strip())
    concepts = getattr(reading_pack_preview, "concepts", ()) or ()
    concept_text = "、".join(str(item) for item in concepts if str(item).strip())
    chapter_items = getattr(reading_pack_preview, "chapter_items", ()) or ()
    chapter_text = "\n".join(f"- {item}" for item in chapter_items if str(item).strip())
    examples = getattr(reading_pack_preview, "examples", ()) or ()
    example_text = "\n".join(f"- {item}" for item in examples if str(item).strip())
    limitations = getattr(reading_pack_preview, "limitations", ()) or ()
    limitation_text = "\n".join(f"- {item}" for item in limitations if str(item).strip())
    source_status = str(getattr(reading_pack_preview, "source_status", "") or "source_missing")
    source_score = getattr(reading_pack_preview, "source_coverage_score", 0) or 0
    source_count = getattr(reading_pack_preview, "source_count", 0) or 0
    artifact_path = str(getattr(reading_pack_preview, "artifact_path", "") or "")
    reading_pack_url = str(getattr(reading_pack_preview, "reading_pack_url", "") or "")
    status = str(getattr(reading_pack_preview, "status", "") or "")
    lines = [
        "**深度读完包**",
        f"来源质量：{source_status} / {source_score}（{source_count} 条来源）",
        f"一句话：{getattr(reading_pack_preview, 'summary', '')}",
    ]
    if concept_text:
        lines.append(f"核心概念：{concept_text}")
    if core_text:
        lines.append(f"论证脉络：\n{core_text}")
    if chapter_text:
        lines.append(f"章节/部分 walkthrough：\n{chapter_text}")
    if example_text:
        lines.append(f"例子/案例：\n{example_text}")
    lines.append(f"10 分钟路径：{getattr(reading_pack_preview, 'ten_min_route', '')}")
    if limitation_text:
        lines.append(f"局限：\n{limitation_text}")
    if artifact_path:
        suffix = f"（{status}）" if status else ""
        lines.append(f"机器归档：`{artifact_path}`{suffix}")
    if reading_pack_url:
        lines.append(f"[打开完整快读包]({reading_pack_url})")
    return [
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}},
    ]
