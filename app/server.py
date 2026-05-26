from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.db import connect, init_db
from app.feedback import (
    FEEDBACK_LABELS,
    FEEDBACK_REASON_LABELS,
    FEEDBACK_REASONS,
    FEEDBACK_TYPES,
    build_feedback_url,
    sign_feedback_free_text,
    verify_feedback_free_text_signature,
    verify_feedback_signature,
)
from app.repository import Repository

logger = logging.getLogger(__name__)
MAX_FREE_TEXT_LENGTH = 500


class FeedbackHandler(BaseHTTPRequestHandler):
    settings: Settings

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._write_text(200, "ok")
            return
        if parsed.path != "/feedback":
            self._write_text(404, "Not Found")
            return
        self._handle_feedback(parse_qs(parsed.query))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/feedback/free-text":
            self._write_text(404, "Not Found")
            return
        self._handle_free_text_submission()

    def log_message(self, fmt: str, *args) -> None:
        logger.info("HTTP " + fmt, *args)

    def _handle_feedback(self, query: dict[str, list[str]]) -> None:
        raw_id = _one(query, "recommendation_id")
        feedback_type = _one(query, "feedback_type")
        reason_code = _one(query, "reason_code") or ""
        token = _one(query, "token")
        try:
            recommendation_id = int(raw_id)
        except (TypeError, ValueError):
            self._write_text(400, "参数错误")
            return
        if feedback_type not in FEEDBACK_TYPES:
            self._write_text(400, "反馈类型无效")
            return
        if reason_code and reason_code not in FEEDBACK_REASONS[feedback_type]:
            self._write_text(400, "原因类型无效")
            return
        if not verify_feedback_signature(recommendation_id, feedback_type, token or "", self.settings.feedback_secret, reason_code):
            self._write_text(403, "签名无效")
            return

        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            if not repo.recommendation_exists(recommendation_id):
                self._write_text(404, "推荐不存在")
                return
            if not reason_code:
                self._write_html(200, _reason_selection_page(self.settings, recommendation_id, feedback_type))
                return
            feedback_id = repo.add_feedback(recommendation_id, feedback_type, reason_code=reason_code)
            self._write_html(200, _feedback_completion_page(self.settings, feedback_id))
        finally:
            conn.close()

    def _handle_free_text_submission(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_text(400, "参数错误")
            return
        raw = self.rfile.read(min(length, 8192)).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        raw_feedback_id = _one(form, "feedback_id")
        token = _one(form, "token") or ""
        try:
            feedback_id = int(raw_feedback_id)
        except (TypeError, ValueError):
            self._write_text(400, "参数错误")
            return
        if not verify_feedback_free_text_signature(feedback_id, token, self.settings.feedback_secret):
            self._write_text(403, "签名无效")
            return
        free_text = (_one(form, "free_text") or "").strip()[:MAX_FREE_TEXT_LENGTH]

        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            if not repo.update_feedback_free_text(feedback_id, free_text):
                self._write_text(404, "反馈不存在")
                return
            self._write_html(200, _feedback_completion_page(self.settings, feedback_id, free_text=free_text, saved=True))
        finally:
            conn.close()

    def _write_text(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_feedback_server(settings: Settings, host: str, port: int) -> None:
    handler = type("ConfiguredFeedbackHandler", (FeedbackHandler,), {"settings": settings})
    server = ThreadingHTTPServer((host, port), handler)
    logger.info("Feedback server listening on %s:%s", host, port)
    server.serve_forever()


def _one(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _reason_selection_page(settings: Settings, recommendation_id: int, feedback_type: str) -> str:
    feedback_label = escape(FEEDBACK_LABELS[feedback_type])
    links = []
    for reason_code in FEEDBACK_REASONS[feedback_type]:
        url = build_feedback_url(
            settings.public_base_url,
            recommendation_id,
            feedback_type,
            settings.feedback_secret,
            reason_code=reason_code,
        )
        label = escape(FEEDBACK_REASON_LABELS[reason_code])
        links.append(f'<a class="reason" href="{escape(url, quote=True)}">{label}</a>')
    reason_links = "".join(links)
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>选择反馈原因</title>"
        "<style>"
        "body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f7f8fa;color:#1f2329;}"
        ".wrap{max-width:560px;margin:0 auto;padding:24px 18px;}"
        "h1{font-size:22px;line-height:1.25;margin:0 0 10px;}"
        "p{font-size:15px;line-height:1.6;margin:0 0 18px;color:#4e5969;}"
        ".reason{display:block;margin:10px 0;padding:14px 16px;border:1px solid #d8dce6;border-radius:8px;background:#fff;color:#1f2329;text-decoration:none;font-size:16px;}"
        ".reason:active{background:#eef2ff;}"
        "</style>"
        "</head>"
        "<body>"
        '<main class="wrap">'
        f"<h1>选择“{feedback_label}”的原因</h1>"
        "<p>请选择最接近的一项，提交后会用于更新阅读画像。</p>"
        f"{reason_links}"
        "</main>"
        "</body>"
        "</html>"
    )


def _feedback_completion_page(settings: Settings, feedback_id: int, free_text: str = "", saved: bool = False) -> str:
    token = sign_feedback_free_text(feedback_id, settings.feedback_secret)
    action = f"{settings.public_base_url.rstrip('/')}/feedback/free-text"
    saved_message = "<p>补充内容已更新。</p>" if saved else ""
    free_text_preview = ""
    if free_text:
        free_text_preview = f'<p class="preview">补充内容：{escape(free_text)}</p>'
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>反馈已记录</title>"
        "<style>"
        "body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f7f8fa;color:#1f2329;}"
        ".wrap{max-width:560px;margin:0 auto;padding:24px 18px;}"
        "h1{font-size:22px;line-height:1.25;margin:0 0 10px;}"
        "p{font-size:15px;line-height:1.6;margin:0 0 18px;color:#4e5969;}"
        "textarea{box-sizing:border-box;width:100%;min-height:120px;padding:12px;border:1px solid #d8dce6;border-radius:8px;font-size:15px;line-height:1.5;background:#fff;color:#1f2329;}"
        "button{margin-top:12px;padding:10px 14px;border:0;border-radius:6px;background:#1f6feb;color:#fff;font-size:15px;}"
        ".preview{padding:12px;border:1px solid #d8dce6;border-radius:8px;background:#fff;white-space:pre-wrap;}"
        "</style>"
        "</head>"
        "<body>"
        '<main class="wrap">'
        "<h1>已记录</h1>"
        "<p>你可以补充一句原因，帮助系统更准确地理解这次反馈。可选，最多 500 字。</p>"
        f"{saved_message}"
        f"{free_text_preview}"
        f'<form method="post" action="{escape(action, quote=True)}">'
        f'<input type="hidden" name="feedback_id" value="{feedback_id}">'
        f'<input type="hidden" name="token" value="{escape(token, quote=True)}">'
        f'<textarea name="free_text" maxlength="{MAX_FREE_TEXT_LENGTH}" placeholder="可选：补充具体原因">{escape(free_text)}</textarea>'
        "<button type=\"submit\">提交补充</button>"
        "</form>"
        "</main>"
        "</body>"
        "</html>"
    )
