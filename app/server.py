from __future__ import annotations

import logging
import json
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from app.config import Settings
from app.db import connect, init_db
from app.feedback import (
    FEEDBACK_LABELS,
    FEEDBACK_REASON_LABELS,
    FEEDBACK_REASONS,
    FEEDBACK_TYPES,
    build_feedback_url,
    build_guided_reading_day_url,
    build_reading_pack_url,
    sign_feedback,
    sign_feedback_free_text,
    verify_feedback_free_text_signature,
    verify_feedback_signature,
    verify_guided_reading_day_signature,
    verify_reading_pack_signature,
)
from app.guided_reading import GuidedReadingError, GuidedReadingService
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
        if parsed.path == "/reading-pack":
            self._handle_reading_pack(parse_qs(parsed.query))
            return
        if parsed.path == "/guided-reading":
            self._handle_guided_reading(parse_qs(parsed.query))
            return
        if parsed.path == "/guided-reading/plans":
            self._handle_guided_reading_plans(parse_qs(parsed.query))
            return
        if parsed.path == "/guided-reading/sources":
            self._handle_guided_reading_sources(parse_qs(parsed.query))
            return
        if parsed.path == "/guided-reading/source":
            self._handle_guided_reading_source_detail(parse_qs(parsed.query))
            return
        if parsed.path != "/feedback":
            self._write_text(404, "Not Found")
            return
        self._handle_feedback(parse_qs(parsed.query))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/guided-reading/feedback":
            self._handle_guided_reading_feedback_submission()
            return
        if parsed.path == "/guided-reading/plans":
            self._handle_guided_reading_plan_submission()
            return
        if parsed.path == "/guided-reading/sources/upload":
            self._handle_guided_reading_source_upload()
            return
        if parsed.path == "/guided-reading/sources/delete":
            self._handle_guided_reading_source_delete()
            return
        if parsed.path == "/feedback/inline":
            self._handle_inline_feedback_submission()
            return
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

    def _handle_reading_pack(self, query: dict[str, list[str]]) -> None:
        raw_id = _one(query, "id")
        token = _one(query, "token") or ""
        try:
            reading_pack_id = int(raw_id)
        except (TypeError, ValueError):
            self._write_text(400, "参数错误")
            return
        if not verify_reading_pack_signature(reading_pack_id, token, self.settings.feedback_secret):
            self._write_text(403, "签名无效")
            return

        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            row = repo.get_reading_pack_page(reading_pack_id)
            if row is None:
                self._write_text(404, "快读包不存在")
                return
            self._write_html(200, _reading_pack_page(self.settings, row, _one(query, "module") or "overview"))
        finally:
            conn.close()

    def _handle_guided_reading(self, query: dict[str, list[str]]) -> None:
        raw_id = _one(query, "day_id")
        token = _one(query, "token") or ""
        try:
            plan_day_id = int(raw_id)
        except (TypeError, ValueError):
            self._write_text(400, "参数错误")
            return
        if not verify_guided_reading_day_signature(plan_day_id, token, self.settings.feedback_secret):
            self._write_text(403, "签名无效")
            return

        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            row = repo.get_guided_reading_day_page(plan_day_id)
            if row is None:
                self._write_text(404, "导读不存在")
                return
            days = repo.reading_plan_days(int(row["plan_id"]))
            repo.add_reading_progress_event(
                int(row["plan_id"]),
                plan_day_id,
                "opened",
                {"day_number": int(row["day_number"])},
            )
            self._write_html(200, _guided_reading_day_page(self.settings, row, days))
        finally:
            conn.close()

    def _handle_guided_reading_plans(self, query: dict[str, list[str]]) -> None:
        admin_token = _one(query, "admin_token") or ""
        if not _verify_admin_token(admin_token, self.settings.feedback_secret):
            self._write_text(403, "签名无效")
            return
        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            plans = repo.list_reading_plans()
            self._write_html(200, _guided_reading_plans_page(self.settings, plans, admin_token))
        finally:
            conn.close()

    def _handle_guided_reading_sources(self, query: dict[str, list[str]]) -> None:
        admin_token = _one(query, "admin_token") or ""
        if not _verify_admin_token(admin_token, self.settings.feedback_secret):
            self._write_text(403, "签名无效")
            return
        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            sources = repo.list_reading_source_files()
            self._write_html(200, _guided_reading_sources_page(self.settings, sources, admin_token))
        finally:
            conn.close()

    def _handle_guided_reading_source_detail(self, query: dict[str, list[str]]) -> None:
        admin_token = _one(query, "admin_token") or ""
        if not _verify_admin_token(admin_token, self.settings.feedback_secret):
            self._write_text(403, "签名无效")
            return
        try:
            source_file_id = int(_one(query, "id") or "")
        except ValueError:
            self._write_text(400, "参数错误")
            return
        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            row = repo.get_reading_source_file(source_file_id)
            if row is None:
                self._write_text(404, "书源不存在")
                return
            preview = ""
            try:
                preview = Path(row["stored_path"]).read_text(encoding="utf-8")[:12000]
            except OSError:
                preview = ""
            self._write_html(200, _guided_reading_source_detail_page(self.settings, row, preview, admin_token))
        finally:
            conn.close()

    def _handle_guided_reading_source_upload(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._write_text(400, "请使用 multipart/form-data 上传")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_text(400, "参数错误")
            return
        if length <= 0 or length > 12 * 1024 * 1024:
            self._write_text(400, "上传过大，v1 限制 10MB 文件")
            return
        raw = self.rfile.read(length)
        try:
            fields, files = _parse_multipart_form(raw, content_type)
        except ValueError as exc:
            self._write_text(400, str(exc))
            return
        admin_token = fields.get("admin_token", "")
        if not _verify_admin_token(admin_token, self.settings.feedback_secret):
            self._write_text(403, "签名无效")
            return
        title = fields.get("title", "").strip()
        author = fields.get("author", "").strip()
        upload = files.get("source_file")
        if not title or upload is None:
            self._write_text(400, "书名和文件不能为空")
            return
        filename, file_bytes = upload
        suffix = Path(filename).suffix.lower()
        if suffix not in {".md", ".txt", ".epub"}:
            self._write_text(400, "v1 只支持 .md / .txt / .epub")
            return
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = Path(tmp.name)
        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            try:
                source_id = GuidedReadingService(repo, library_dir=Path(getattr(self.settings, "reading_pack_library_dir", None) or "library")).import_source_file(
                    tmp_path,
                    title=title,
                    author=author,
                    original_filename=filename,
                )
            except GuidedReadingError as exc:
                self._write_text(400, str(exc))
                return
            url = f"{self.settings.public_base_url.rstrip()}/guided-reading/source?{urlencode({'id': source_id, 'admin_token': admin_token})}"
            self._write_html(200, _guided_reading_source_uploaded_page(url, source_id))
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            conn.close()

    def _handle_guided_reading_source_delete(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_text(400, "参数错误")
            return
        raw = self.rfile.read(min(length, 8192)).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        admin_token = _one(form, "admin_token") or ""
        if not _verify_admin_token(admin_token, self.settings.feedback_secret):
            self._write_text(403, "签名无效")
            return
        try:
            source_file_id = int(_one(form, "source_file_id") or "")
        except ValueError:
            self._write_text(400, "参数错误")
            return
        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            if not repo.mark_reading_source_file_deleted(source_file_id):
                self._write_text(404, "书源不存在")
                return
            url = f"{self.settings.public_base_url.rstrip()}/guided-reading/sources?{urlencode({'admin_token': admin_token})}"
            self._write_html(200, _redirect_like_page("书源已删除", url, "回到书源管理"))
        finally:
            conn.close()

    def _handle_guided_reading_plan_submission(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_text(400, "参数错误")
            return
        raw = self.rfile.read(min(length, 1024 * 1024)).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        admin_token = _one(form, "admin_token") or ""
        if not _verify_admin_token(admin_token, self.settings.feedback_secret):
            self._write_text(403, "签名无效")
            return
        title = (_one(form, "title") or "").strip()
        author = (_one(form, "author") or "").strip()
        source_text = (_one(form, "source_text") or "").strip()
        raw_source_file_id = _one(form, "source_file_id") or ""
        mode = _one(form, "mode") or "guided"
        tone = _one(form, "tone") or "short_video"
        spoiler_policy = _one(form, "spoiler_policy") or "avoid"
        lark_push_enabled = (_one(form, "lark_push_enabled") or "") == "1"
        try:
            plan_days = int(_one(form, "plan_days") or "5")
            daily_minutes = int(_one(form, "daily_minutes") or "8")
        except ValueError:
            self._write_text(400, "参数错误")
            return
        if not title:
            self._write_text(400, "书名不能为空")
            return

        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            try:
                service = GuidedReadingService(repo, library_dir=Path(getattr(self.settings, "reading_pack_library_dir", None) or "library"))
                if raw_source_file_id:
                    result = service.create_plan_from_source_file(
                        source_file_id=int(raw_source_file_id),
                        plan_days=plan_days,
                        daily_minutes=daily_minutes,
                        mode=mode,
                        tone=tone,
                        spoiler_policy=spoiler_policy,
                        lark_push_enabled=lark_push_enabled,
                    )
                else:
                    result = service.create_plan_from_text(
                        source_text=source_text,
                        title=title,
                        author=author,
                        plan_days=plan_days,
                        daily_minutes=daily_minutes,
                        mode=mode,
                        tone=tone,
                        spoiler_policy=spoiler_policy,
                        lark_push_enabled=lark_push_enabled,
                    )
            except GuidedReadingError as exc:
                self._write_text(400, str(exc))
                return
            url = build_guided_reading_day_url(self.settings.public_base_url, result.first_day_id, self.settings.feedback_secret)
            self._write_html(200, _guided_reading_plan_created_page(url, result.plan_id))
        finally:
            conn.close()

    def _handle_guided_reading_feedback_submission(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_text(400, "参数错误")
            return
        raw = self.rfile.read(min(length, 8192)).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        raw_day_id = _one(form, "day_id")
        token = _one(form, "token") or ""
        event_type = _one(form, "event_type") or ""
        note = (_one(form, "note") or "").strip()[:MAX_FREE_TEXT_LENGTH]
        try:
            plan_day_id = int(raw_day_id)
        except (TypeError, ValueError):
            self._write_text(400, "参数错误")
            return
        if event_type not in {"too_long", "not_interested", "just_right", "continue", "completed"}:
            self._write_text(400, "反馈类型无效")
            return
        if not verify_guided_reading_day_signature(plan_day_id, token, self.settings.feedback_secret):
            self._write_text(403, "签名无效")
            return

        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            row = repo.get_guided_reading_day_page(plan_day_id)
            if row is None:
                self._write_text(404, "导读不存在")
                return
            if event_type == "completed":
                repo.mark_reading_plan_day_completed(plan_day_id)
            repo.add_reading_progress_event(
                int(row["plan_id"]),
                plan_day_id,
                event_type,
                {"note": note, "day_number": int(row["day_number"])},
            )
            return_url = build_guided_reading_day_url(self.settings.public_base_url, plan_day_id, self.settings.feedback_secret)
            self._write_html(200, _guided_reading_feedback_saved_page(return_url, event_type))
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

    def _handle_inline_feedback_submission(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_text(400, "参数错误")
            return
        raw = self.rfile.read(min(length, 8192)).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        raw_recommendation_id = _one(form, "recommendation_id")
        feedback_type = _one(form, "feedback_type")
        reason_choice = _one(form, "reason_choice") or ""
        return_url = _one(form, "return_url") or self.settings.public_base_url
        try:
            recommendation_id = int(raw_recommendation_id)
        except (TypeError, ValueError):
            self._write_text(400, "参数错误")
            return
        if feedback_type not in FEEDBACK_TYPES:
            self._write_text(400, "反馈类型无效")
            return
        try:
            reason_code, token = reason_choice.split(".", 1)
        except ValueError:
            self._write_text(400, "原因参数无效")
            return
        if reason_code not in FEEDBACK_REASONS[feedback_type]:
            self._write_text(400, "原因类型无效")
            return
        if not verify_feedback_signature(recommendation_id, feedback_type, token, self.settings.feedback_secret, reason_code):
            self._write_text(403, "签名无效")
            return
        free_text = (_one(form, "free_text") or "").strip()[:MAX_FREE_TEXT_LENGTH]

        conn = connect(self.settings.database_path)
        try:
            init_db(conn)
            repo = Repository(conn)
            if not repo.recommendation_exists(recommendation_id):
                self._write_text(404, "推荐不存在")
                return
            feedback_id = repo.add_feedback(
                recommendation_id,
                feedback_type,
                reason_code=reason_code,
                free_text=free_text,
            )
            self._write_html(200, _inline_feedback_saved_page(return_url, feedback_id))
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
        ":root{--paper:#fffdf8;--canvas:#f3efe6;--ink:#23251f;--muted:#6c6a61;--line:#ded7ca;--accent:#46615b;--accent-soft:#e5ece8;}"
        "body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}"
        ".wrap{max-width:560px;margin:0 auto;padding:24px 18px;}"
        "h1{font-size:22px;line-height:1.25;margin:0 0 10px;}"
        "p{font-size:15px;line-height:1.6;margin:0 0 18px;color:var(--muted);}"
        ".reason{display:block;margin:10px 0;padding:14px 16px;border:1px solid var(--line);border-radius:8px;background:var(--paper);color:var(--ink);text-decoration:none;font-size:16px;box-shadow:0 6px 18px rgba(66,54,32,.05);transition:background .16s ease,transform .16s ease;}"
        ".reason:active,.reason:hover{background:var(--accent-soft);transform:translateY(-1px);}"
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
        ":root{--paper:#fffdf8;--canvas:#f3efe6;--ink:#23251f;--muted:#6c6a61;--line:#ded7ca;--accent:#46615b;--accent-soft:#e5ece8;}"
        "body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}"
        ".wrap{max-width:560px;margin:0 auto;padding:24px 18px;}"
        "h1{font-size:22px;line-height:1.25;margin:0 0 10px;}"
        "p{font-size:15px;line-height:1.6;margin:0 0 18px;color:var(--muted);}"
        "textarea{box-sizing:border-box;width:100%;min-height:120px;padding:12px;border:1px solid var(--line);border-radius:8px;font-size:15px;line-height:1.5;background:var(--paper);color:var(--ink);}"
        "button{margin-top:12px;padding:10px 14px;border:0;border-radius:6px;background:var(--accent);color:#fff;font-size:15px;}"
        ".preview{padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--paper);white-space:pre-wrap;}"
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


def _reading_pack_page(settings: Settings, row, current_module: str) -> str:
    content = _json_loads(row["content_json"], {})
    artifact_metadata = _json_loads(row["artifact_metadata_json"], {})
    module_paths = artifact_metadata.get("module_paths", []) if isinstance(artifact_metadata, dict) else []
    recommendation_id = int(row["recommendation_id"])
    modules = _reading_pack_modules(content)
    current_index = _module_index(modules, current_module)
    current_slug, current_label, current_sections = modules[current_index]
    current_url = _reading_pack_module_url(settings, int(row["id"]), current_slug)
    feedback_panel = _inline_feedback_panel(settings, recommendation_id, current_url)
    module_nav = _module_nav(settings, int(row["id"]), modules, current_index, module_paths)
    overview_panel = _reading_overview_panel(settings, int(row["id"]), modules, current_index)
    section_items = _prepare_current_sections(current_slug, current_sections)
    intro_panel = _module_intro_panel(current_slug, current_label, section_items)
    section_nav = _section_nav_panel(section_items)
    body = "".join(item["html"] for item in section_items)
    pager = _module_pager(settings, int(row["id"]), modules, current_index)
    title = f"{row['book_title']} 快读包"
    subtitle = f"{row['book_author']} · {row['status']} · {row['generator_provider']} · {current_label} {current_index + 1}/{len(modules)}"
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        "<style>"
        ":root{--paper:#fffdf8;--canvas:#f3efe6;--ink:#23251f;--muted:#6c6a61;--line:#ded7ca;--accent:#46615b;--accent-soft:#e5ece8;--warn:#8a6b3d;}"
        "*{box-sizing:border-box;}"
        "html,body{max-width:100%;overflow-x:hidden;}"
        "body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}"
        "body:before{content:'';position:fixed;inset:0;pointer-events:none;background:linear-gradient(180deg,rgba(255,255,255,.54),rgba(255,255,255,0) 220px);}"
        ".wrap{width:100%;max-width:940px;margin:0 auto;padding:34px 18px 72px;overflow-x:hidden;}"
        "h1{font-size:30px;line-height:1.22;margin:0 0 8px;font-weight:720;letter-spacing:0;}"
        ".meta{font-size:14px;color:var(--muted);margin:0 0 22px;}"
        ".modules{display:flex;max-width:100%;min-width:0;gap:8px;overflow-x:auto;margin:0 0 20px;padding:0 0 6px;scrollbar-width:thin;-webkit-overflow-scrolling:touch;}"
        ".module{max-width:78vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:8px 11px;border:1px solid var(--line);border-radius:7px;background:rgba(255,253,248,.78);color:var(--accent);font-size:13px;box-shadow:0 1px 1px rgba(44,38,26,.04);text-decoration:none;}"
        ".module.active{background:var(--accent);color:#fff;border-color:var(--accent);}"
        ".scroll-progress{position:fixed;top:0;left:0;right:0;height:4px;background:rgba(222,215,202,.62);z-index:10;}"
        ".scroll-progress span{display:block;height:100%;width:0;background:var(--accent);transition:width .08s linear;}"
        ".progress{height:7px;border:1px solid var(--line);border-radius:999px;background:#ede5d8;margin:0 0 20px;overflow:hidden;}"
        ".bar{display:block;height:100%;background:var(--accent);}"
        ".toc{margin:0 0 20px;padding:14px;border:1px solid var(--line);border-radius:8px;background:rgba(255,253,248,.72);}"
        ".toc-title{margin:0 0 10px;font-size:15px;color:var(--muted);}"
        ".toc-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;}"
        ".toc-card{min-width:0;min-height:92px;padding:11px;border:1px solid var(--line);border-radius:8px;background:var(--paper);color:var(--ink);text-decoration:none;overflow-wrap:anywhere;transition:transform .16s ease,box-shadow .16s ease;}"
        ".toc-card:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(66,54,32,.07);}"
        ".toc-card.active{border-color:var(--accent);background:var(--accent-soft);}"
        ".toc-card strong{display:block;margin-bottom:6px;font-size:14px;color:var(--accent);}"
        ".toc-card span{display:block;font-size:12px;line-height:1.45;color:var(--muted);}"
        ".module-brief{margin:0 0 18px;padding:18px;border:1px solid var(--line);border-radius:8px;background:#f8f4eb;box-shadow:0 8px 24px rgba(66,54,32,.05);}"
        ".brief-top{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:10px;}"
        ".brief-kicker{margin:0 0 5px;font-size:12px;color:var(--accent);font-weight:700;}"
        ".brief-title{margin:0;font-size:19px;line-height:1.32;color:var(--ink);}"
        ".brief-time{flex:0 0 auto;padding:6px 9px;border:1px solid #cfc7b9;border-radius:999px;background:var(--paper);color:var(--muted);font-size:12px;}"
        ".brief-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:12px;}"
        ".brief-item{min-width:0;padding:10px;border:1px solid rgba(222,215,202,.9);border-radius:8px;background:rgba(255,253,248,.72);overflow-wrap:anywhere;}"
        ".brief-item strong{display:block;margin-bottom:4px;font-size:12px;color:#7a6036;}"
        ".brief-item span{display:block;font-size:13px;line-height:1.48;color:var(--muted);}"
        ".reading-layout{display:grid;grid-template-columns:minmax(0,1fr) 220px;gap:18px;align-items:start;}"
        ".reading-flow{min-width:0;}"
        ".section-rail{max-width:100%;min-width:0;position:sticky;top:18px;padding:12px;border:1px solid var(--line);border-radius:8px;background:rgba(255,253,248,.76);box-shadow:0 8px 24px rgba(66,54,32,.05);}"
        ".rail-title{margin:0 0 8px;font-size:13px;color:var(--muted);}"
        ".rail-link{display:block;margin:6px 0;padding:8px;border-radius:7px;color:var(--accent);font-size:13px;line-height:1.35;text-decoration:none;transition:background .16s ease,color .16s ease;}"
        ".rail-link:hover{background:var(--accent-soft);color:#263d38;}"
        ".content-section{max-width:100%;scroll-margin-top:14px;margin:0 0 18px;padding:26px 26px;border:1px solid var(--line);border-radius:8px;background:var(--paper);overflow-wrap:anywhere;box-shadow:0 10px 28px rgba(66,54,32,.06),0 1px 0 rgba(255,255,255,.8) inset;}"
        ".content-section:hover{box-shadow:0 14px 34px rgba(66,54,32,.08),0 1px 0 rgba(255,255,255,.8) inset;transition:box-shadow .18s ease;}"
        ".section-thesis{border-left:4px solid #46615b;}"
        ".section-route{border-left:4px solid #8a6b3d;}"
        ".section-case{border-left:4px solid #6f7f5a;}"
        ".section-limit{border-left:4px solid #9a6d64;}"
        "h2{font-size:18px;margin:0 0 12px;line-height:1.35;color:#30342e;font-weight:700;}"
        "p,li{font-size:16px;line-height:1.78;word-break:break-word;}"
        ".text-paragraph{margin:0 0 13px;}"
        ".text-paragraph:last-child{margin-bottom:0;}"
        "ul,ol{padding-left:22px;margin:8px 0 0;}"
        "li+li{margin-top:10px;}"
        ".li-part{display:block;margin-top:6px;}"
        ".li-part:first-child{margin-top:0;}"
        ".li-part b{color:#4f5049;}"
        ".feedbacks{position:sticky;bottom:0;width:calc(100% + 36px);max-width:100vw;margin:28px -18px -72px;padding:12px 18px;background:rgba(243,239,230,.96);border-top:1px solid var(--line);display:flex;gap:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;backdrop-filter:blur(10px);}"
        ".feedback-group{min-width:176px;border:1px solid #cfc7b9;border-radius:8px;background:var(--paper);}"
        ".feedback-group summary{cursor:pointer;list-style:none;padding:10px 12px;color:var(--accent);font-size:14px;}"
        ".feedback-group summary::-webkit-details-marker{display:none;}"
        ".feedback-form{padding:0 10px 10px;}"
        ".feedback-form textarea{width:100%;min-height:58px;resize:vertical;border:1px solid var(--line);border-radius:7px;background:#fffefb;color:var(--ink);font-size:13px;line-height:1.45;padding:8px;}"
        ".reason-buttons{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;}"
        ".reason-buttons button{border:1px solid #cfc7b9;border-radius:7px;background:var(--accent-soft);color:#2f4741;padding:7px 8px;font-size:12px;}"
        ".pager{display:flex;justify-content:space-between;gap:10px;margin:22px 0 4px;}"
        ".pager a,.pager span{min-width:0;flex:1;padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--paper);color:var(--accent);text-decoration:none;text-align:left;overflow-wrap:anywhere;}"
        ".pager span{color:var(--muted);background:rgba(255,253,248,.54);}"
        ".pager strong,.pager small{display:block;}"
        ".pager small{margin-top:4px;color:var(--muted);font-size:12px;line-height:1.4;}"
        "@media(max-width:820px){.reading-layout{display:flex;flex-direction:column;}.section-rail{order:-1;position:static;margin:0 0 16px;overflow-x:auto;white-space:nowrap;-webkit-overflow-scrolling:touch;}.rail-title{display:inline-block;margin:0 8px 0 0;}.rail-link{display:inline-block;max-width:62vw;margin:0 4px 0 0;overflow:hidden;text-overflow:ellipsis;vertical-align:middle;}.brief-grid{grid-template-columns:1fr;}.toc-grid{grid-template-columns:1fr 1fr;}.toc-card{min-height:84px;}.pager{margin-bottom:18px;}.feedbacks{position:static;width:100%;max-width:100%;margin:18px 0 0;padding:12px 0 0;background:transparent;border-top:1px solid var(--line);display:block;overflow:visible;backdrop-filter:none;}.feedback-group{width:100%;min-width:0;margin:0 0 8px;}.feedback-form{padding:0 12px 12px;}.reason-buttons button{flex:1 1 calc(50% - 6px);}}"
        "@media(max-width:640px){.wrap{padding:24px 14px 68px;}h1{font-size:24px;}.meta{font-size:13px;line-height:1.5;}.content-section{padding:18px 16px;}p,li{font-size:15px;line-height:1.74;}.toc-grid{grid-template-columns:1fr;}.brief-top{display:block;}.brief-time{display:inline-block;margin-top:10px;}.pager{display:block;}.pager a,.pager span{display:block;margin-bottom:8px;}.feedbacks{width:calc(100% + 28px);margin-left:-14px;margin-right:-14px;padding:10px 14px;}.feedback-group{min-width:154px;}}"
        "</style>"
        "</head>"
        "<body>"
        '<div class="scroll-progress" aria-hidden="true"><span id="scrollBar"></span></div>'
        '<main class="wrap">'
        f"<h1>{escape(title)}</h1>"
        f'<p class="meta">{escape(subtitle)}</p>'
        f"{module_nav}"
        f'<div class="progress" aria-label="阅读进度"><span class="bar" style="width:{round(((current_index + 1) / len(modules)) * 100, 1)}%"></span></div>'
        f"{overview_panel}"
        f"{intro_panel}"
        '<div class="reading-layout">'
        f'<article class="reading-flow">{body}</article>'
        f"{section_nav}"
        "</div>"
        f"{pager}"
        f"{feedback_panel}"
        "</main>"
        "<script>"
        "function updateScrollBar(){var d=document.documentElement;var max=d.scrollHeight-d.clientHeight;var pct=max>0?(d.scrollTop/max)*100:100;var bar=document.getElementById('scrollBar');if(bar){bar.style.width=pct+'%';}}"
        "document.addEventListener('scroll',updateScrollBar,{passive:true});window.addEventListener('resize',updateScrollBar);updateScrollBar();"
        "</script>"
        "</body>"
        "</html>"
    )


def _reading_pack_modules(content: dict) -> list[tuple[str, str, list[str]]]:
    return [
        (
            "overview",
            "总览",
            [
                _section("一句话主张", content.get("one_sentence_thesis")),
                _section("定位", content.get("book_positioning")),
                _section("作者项目", content.get("author_project")),
                _section("来源说明", content.get("source_note")),
            ],
        ),
        (
            "argument",
            "论证",
            [
                _list_section("论证链", content.get("expanded_argument")),
                _section("心智模型", content.get("mental_model_map")),
            ],
        ),
        ("walkthrough", "章节", [_walkthrough_section(content.get("part_walkthrough"))]),
        (
            "concepts-cases",
            "概念案例",
            [
                _list_section("案例库", content.get("story_case_bank")),
                _concept_section(content.get("concept_cards")),
            ],
        ),
        (
            "application",
            "应用",
            [
                _section("跳过原书会错过什么", content.get("what_you_would_miss_if_skipping_full_book")),
                _section("10 分钟路线", content.get("ten_min_absorption_path")),
                _section("30 分钟路线", content.get("thirty_min_absorption_path")),
                _section("2 小时路线", content.get("two_hour_absorption_path")),
                _section("用户应用手册", content.get("user_application_playbook")),
                _list_section("局限", content.get("limitations")),
            ],
        ),
    ]


def _module_index(modules: list[tuple[str, str, list[str]]], current_module: str) -> int:
    for index, (slug, _, _) in enumerate(modules):
        if slug == current_module:
            return index
    return 0


def _module_nav(settings: Settings, reading_pack_id: int, modules: list[tuple[str, str, list[str]]], current_index: int, module_paths) -> str:
    items = []
    for index, (slug, label, _) in enumerate(modules):
        path = module_paths[index] if isinstance(module_paths, list) and index < len(module_paths) else ""
        detail = f" · {path}" if path else ""
        active = " active" if index == current_index else ""
        url = _reading_pack_module_url(settings, reading_pack_id, slug)
        items.append(f'<a class="module{active}" href="{escape(url, quote=True)}">{escape(label)}{escape(str(detail))}</a>')
    return f'<nav class="modules" aria-label="模块">{"".join(items)}</nav>'


def _reading_overview_panel(settings: Settings, reading_pack_id: int, modules: list[tuple[str, str, list[str]]], current_index: int) -> str:
    cards = []
    for index, (slug, label, _) in enumerate(modules):
        active = " active" if index == current_index else ""
        url = _reading_pack_module_url(settings, reading_pack_id, slug)
        cards.append(
            f'<a class="toc-card{active}" href="{escape(url, quote=True)}">'
            f"<strong>{index + 1}. {escape(label)}</strong>"
            f"<span>{escape(_module_description(slug))}</span>"
            "</a>"
        )
    return '<section class="toc"><p class="toc-title">全书总览</p><div class="toc-grid">' + "".join(cards) + "</div></section>"


def _module_pager(settings: Settings, reading_pack_id: int, modules: list[tuple[str, str, list[str]]], current_index: int) -> str:
    prev_item = "<span>上一页</span>"
    next_item = "<span>下一页</span>"
    if current_index > 0:
        slug, label, _ = modules[current_index - 1]
        prev_item = (
            f'<a href="{escape(_reading_pack_module_url(settings, reading_pack_id, slug), quote=True)}">'
            f"<strong>上一页：{escape(label)}</strong>"
            f"<small>{escape(_module_description(slug))}</small>"
            "</a>"
        )
    if current_index < len(modules) - 1:
        slug, label, _ = modules[current_index + 1]
        next_item = (
            f'<a href="{escape(_reading_pack_module_url(settings, reading_pack_id, slug), quote=True)}">'
            f"<strong>下一页：{escape(label)}</strong>"
            f"<small>{escape(_module_description(slug))}</small>"
            "</a>"
        )
    return f'<nav class="pager" aria-label="分页">{prev_item}{next_item}</nav>'


def _module_description(slug: str) -> str:
    descriptions = {
        "overview": "本书定位、作者项目、核心主张和来源边界。",
        "argument": "完整论证链和心智模型，适合建立全局框架。",
        "walkthrough": "按章节/部分穿过全书结构，知道下一页会展开哪里。",
        "concepts-cases": "核心概念卡、案例和可识别的工程信号。",
        "application": "阅读路线、应用手册、局限和行动问题。",
    }
    return descriptions.get(slug, "")


def _module_takeaway(slug: str) -> str:
    takeaways = {
        "overview": "先建立判断这本书是否值得深入的边界感。",
        "argument": "抓住作者如何把问题、机制和结论串起来。",
        "walkthrough": "知道原书结构如何推进，避免只记住抽象结论。",
        "concepts-cases": "把概念和案例转成能识别、能复用的信号。",
        "application": "把快读结果转成下一步阅读、实践或放弃的决策。",
    }
    return takeaways.get(slug, "读完后能更清楚地决定下一步。")


def _module_intro_panel(slug: str, label: str, section_items: list[dict[str, str]]) -> str:
    section_titles = [item["title"] for item in section_items]
    includes = "、".join(section_titles[:4]) if section_titles else "本模块内容"
    minutes = _reading_minutes("".join(item["plain_text"] for item in section_items))
    return (
        '<section class="module-brief" aria-label="本页导读">'
        '<div class="brief-top">'
        "<div>"
        '<p class="brief-kicker">本页导读</p>'
        f'<h2 class="brief-title">{escape(label)}：{escape(_module_description(slug))}</h2>'
        "</div>"
        f'<span class="brief-time">约 {minutes} 分钟</span>'
        "</div>"
        '<div class="brief-grid">'
        f'<div class="brief-item"><strong>本页解决</strong><span>{escape(_module_description(slug))}</span></div>'
        f'<div class="brief-item"><strong>包含内容</strong><span>{escape(includes)}</span></div>'
        f'<div class="brief-item"><strong>读完带走</strong><span>{escape(_module_takeaway(slug))}</span></div>'
        "</div>"
        "</section>"
    )


def _section_nav_panel(section_items: list[dict[str, str]]) -> str:
    if not section_items:
        return ""
    links = "".join(
        f'<a class="rail-link" href="#{escape(item["id"], quote=True)}">{escape(item["title"])}</a>' for item in section_items
    )
    return f'<aside class="section-rail" aria-label="页内目录"><p class="rail-title">页内目录</p>{links}</aside>'


def _prepare_current_sections(slug: str, sections: list[str]) -> list[dict[str, str]]:
    items = []
    for section in sections:
        if not section:
            continue
        title = _extract_h2(section) or f"第 {len(items) + 1} 节"
        section_id = f"{slug}-{len(items) + 1}"
        css_class = f"content-section {_section_kind(title)}".strip()
        html = section.replace("<section>", f'<section id="{section_id}" class="{css_class}">', 1)
        items.append(
            {
                "id": section_id,
                "title": title,
                "html": html,
                "plain_text": _html_to_text(section),
            }
        )
    return items


def _extract_h2(html: str) -> str:
    start = html.find("<h2>")
    end = html.find("</h2>", start)
    if start < 0 or end < 0:
        return ""
    return html[start + 4 : end]


def _section_kind(title: str) -> str:
    if any(keyword in title for keyword in ("主张", "定位", "心智模型")):
        return "section-thesis"
    if any(keyword in title for keyword in ("路线", "手册")):
        return "section-route"
    if any(keyword in title for keyword in ("案例", "概念", "Walkthrough")):
        return "section-case"
    if any(keyword in title for keyword in ("局限", "错过")):
        return "section-limit"
    return ""


def _reading_minutes(text: str) -> int:
    length = len("".join(text.split()))
    return max(1, round(length / 450))


def _html_to_text(html: str) -> str:
    chars = []
    in_tag = False
    for char in html:
        if char == "<":
            in_tag = True
            continue
        if char == ">":
            in_tag = False
            chars.append(" ")
            continue
        if not in_tag:
            chars.append(char)
    return " ".join("".join(chars).split())


def _reading_pack_module_url(settings: Settings, reading_pack_id: int, module: str) -> str:
    base_url = build_reading_pack_url(settings.public_base_url, reading_pack_id, settings.feedback_secret)
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({'module': module})}"


def _inline_feedback_panel(settings: Settings, recommendation_id: int, return_url: str) -> str:
    groups = []
    for feedback_type in ("like", "neutral", "not_interested", "already_read", "go_deeper"):
        buttons = []
        for reason_code in FEEDBACK_REASONS[feedback_type]:
            token = sign_feedback(recommendation_id, feedback_type, settings.feedback_secret, reason_code)
            value = f"{reason_code}.{token}"
            buttons.append(
                f'<button type="submit" name="reason_choice" value="{escape(value, quote=True)}">{escape(FEEDBACK_REASON_LABELS[reason_code])}</button>'
            )
        groups.append(
            "<details class=\"feedback-group\">"
            f"<summary>{escape(FEEDBACK_LABELS[feedback_type])}</summary>"
            '<form class="feedback-form" method="post" action="/feedback/inline">'
            f'<input type="hidden" name="recommendation_id" value="{recommendation_id}">'
            f'<input type="hidden" name="feedback_type" value="{escape(feedback_type, quote=True)}">'
            f'<input type="hidden" name="return_url" value="{escape(return_url, quote=True)}">'
            f'<textarea name="free_text" maxlength="{MAX_FREE_TEXT_LENGTH}" placeholder="可选：补充一句原因"></textarea>'
            f'<div class="reason-buttons">{"".join(buttons)}</div>'
            "</form>"
            "</details>"
        )
    return f'<nav class="feedbacks" aria-label="反馈">{"".join(groups)}</nav>'


def _inline_feedback_saved_page(return_url: str, feedback_id: int) -> str:
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>反馈已记录</title>"
        "<style>"
        ":root{--paper:#fffdf8;--canvas:#f3efe6;--ink:#23251f;--muted:#6c6a61;--line:#ded7ca;--accent:#46615b;--accent-soft:#e5ece8;}"
        "body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}"
        ".wrap{max-width:560px;margin:0 auto;padding:28px 18px;}"
        "h1{font-size:24px;margin:0 0 10px;}"
        "p{font-size:15px;line-height:1.65;color:var(--muted);}"
        "a{display:inline-block;margin-top:8px;padding:10px 12px;border:1px solid var(--line);border-radius:7px;background:var(--paper);color:var(--accent);text-decoration:none;}"
        "</style>"
        "</head>"
        "<body>"
        '<main class="wrap">'
        "<h1>反馈已记录</h1>"
        f"<p>反馈 #{feedback_id} 已写入画像事实层。</p>"
        f'<a href="{escape(return_url, quote=True)}">回到快读包</a>'
        "</main>"
        "</body>"
        "</html>"
    )


def _guided_reading_day_page(settings: Settings, row, days) -> str:
    content = _json_loads(row["content_json"], {})
    plan_day_id = int(row["id"])
    token_url = build_guided_reading_day_url(settings.public_base_url, plan_day_id, settings.feedback_secret)
    token = _one(parse_qs(urlparse(token_url).query), "token") or ""
    day_number = int(row["day_number"])
    total_days = int(row["plan_days"])
    source_text = row["source_text"] or ""
    mode = row["mode"] or "guided"
    is_drama = mode == "drama" or row["tone"] == "drama"
    title = f"{row['book_title']} Day {day_number} 导读"
    progress_width = round((day_number / max(1, total_days)) * 100, 1)
    day_links = []
    for day in days:
        day_id = int(day["id"])
        active = " active" if day_id == plan_day_id else ""
        url = build_guided_reading_day_url(settings.public_base_url, day_id, settings.feedback_secret)
        day_links.append(
            f'<a class="day-pill{active}" href="{escape(url, quote=True)}">Day {int(day["day_number"])}</a>'
        )
    feedback = _guided_reading_feedback_panel(plan_day_id, token)
    key_points = "".join(f"<li>{escape(str(item))}</li>" for item in content.get("key_points", []))
    source_paragraphs = "".join(f'<p class="source-p">{escape(part)}</p>' for part in _text_paragraphs(source_text))
    spoiler_badge = '<span class="badge">不剧透已开启</span>' if is_drama and row["spoiler_policy"] == "avoid" else ""
    drama_panel = ""
    if is_drama:
        drama_panel = (
            '<section class="episode-panel">'
            "<h2>追剧式续上</h2>"
            f"<p>{escape(content.get('why_it_matters', ''))}</p>"
            f"<p><strong>今天只盯一个变化：</strong>{escape(content.get('one_question', ''))}</p>"
            "</section>"
        )
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        "<style>"
        ":root{--paper:#fffdf8;--canvas:#f1eee7;--ink:#24251f;--muted:#706d63;--line:#ddd5c8;--accent:#3f635c;--accent-soft:#e3ece8;--amber:#8a6b3d;--rose:#8f5f58;}"
        "*{box-sizing:border-box;}html,body{max-width:100%;overflow-x:hidden;}body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}"
        ".wrap{width:100%;max-width:980px;margin:0 auto;padding:20px 16px 64px;}"
        ".top{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin:6px 0 16px;}"
        ".kicker{margin:0 0 6px;color:var(--accent);font-size:13px;font-weight:700;}"
        "h1{margin:0;font-size:28px;line-height:1.22;letter-spacing:0;}.meta{margin:8px 0 0;color:var(--muted);font-size:14px;line-height:1.5;}"
        ".badge{display:inline-flex;align-items:center;white-space:nowrap;padding:7px 9px;border:1px solid #c7bda9;border-radius:999px;background:var(--paper);color:var(--amber);font-size:12px;}"
        ".progress{height:8px;border:1px solid var(--line);border-radius:999px;background:#e7dfd2;margin:0 0 14px;overflow:hidden;}.bar{display:block;height:100%;background:var(--accent);}"
        ".days{display:flex;gap:8px;overflow-x:auto;padding:0 0 8px;margin:0 0 18px;-webkit-overflow-scrolling:touch;}.day-pill{padding:8px 10px;border:1px solid var(--line);border-radius:7px;background:rgba(255,253,248,.78);color:var(--accent);font-size:13px;text-decoration:none;white-space:nowrap;}.day-pill.active{background:var(--accent);border-color:var(--accent);color:#fff;}"
        ".hero{padding:22px;border:1px solid var(--line);border-radius:8px;background:var(--paper);box-shadow:0 14px 34px rgba(69,57,37,.07);}.hero h2{margin:0 0 12px;font-size:22px;line-height:1.28;}.hero p{margin:0;color:#3e433b;font-size:17px;line-height:1.72;}"
        ".actions{display:flex;flex-wrap:wrap;gap:9px;margin-top:16px;}.button{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:10px 13px;border:1px solid var(--accent);border-radius:7px;background:var(--accent);color:#fff;text-decoration:none;font-size:14px;}.button.secondary{background:var(--paper);color:var(--accent);}"
        ".grid{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:18px;margin-top:18px;align-items:start;}.main{min-width:0;}.side{position:sticky;top:14px;min-width:0;}"
        ".panel{margin:0 0 14px;padding:18px;border:1px solid var(--line);border-radius:8px;background:rgba(255,253,248,.84);box-shadow:0 8px 24px rgba(69,57,37,.045);}.panel h2,.episode-panel h2{margin:0 0 10px;font-size:18px;line-height:1.35;}.panel p,.panel li,.episode-panel p{font-size:16px;line-height:1.75;color:#3f413a;}.panel p{margin:0 0 10px;}.panel p:last-child{margin-bottom:0;}ol,ul{padding-left:22px;margin:8px 0 0;}li+li{margin-top:8px;}"
        ".question{border-left:4px solid var(--accent);}.source-box{padding:0;overflow:hidden;}.source-head{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:16px 18px;border-bottom:1px solid var(--line);}.source-head h2{margin:0;font-size:18px;}.source-content{padding:18px;background:#fffdf8;}.source-p{margin:0 0 14px;font-size:17px;line-height:1.86;color:#262820;}.source-p:last-child{margin-bottom:0;}"
        "details.source-details summary{cursor:pointer;list-style:none;color:var(--accent);font-size:14px;}details.source-details summary::-webkit-details-marker{display:none;}"
        ".episode-panel{margin:0 0 14px;padding:18px;border:1px solid #d8cbb7;border-radius:8px;background:#f9f1df;}"
        ".feedback-card{padding:16px;border:1px solid var(--line);border-radius:8px;background:var(--paper);}.feedback-card h2{margin:0 0 8px;font-size:16px;}.feedback-card p{margin:0 0 10px;color:var(--muted);font-size:13px;line-height:1.55;}.feedback-card textarea{width:100%;min-height:68px;resize:vertical;padding:9px;border:1px solid var(--line);border-radius:7px;background:#fffefb;color:var(--ink);font-size:13px;line-height:1.5;}.feedback-buttons{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:9px;}.feedback-buttons button{min-height:38px;border:1px solid #c9bdab;border-radius:7px;background:var(--accent-soft);color:#294640;font-size:13px;}.feedback-buttons button.primary{background:var(--accent);border-color:var(--accent);color:#fff;}"
        "@media(max-width:820px){.grid{display:block;}.side{position:static;margin-top:16px;}.hero{padding:20px 18px;}.hero h2{font-size:21px;}.feedback-buttons{grid-template-columns:1fr;}}"
        "@media(max-width:560px){.wrap{padding:16px 13px 52px;}.top{display:block;}h1{font-size:24px;}.badge{margin-top:10px;}.hero p,.source-p{font-size:16px;}.panel{padding:16px;}.actions{display:block;}.button{width:100%;margin-top:8px;}.source-head{display:block;}.source-head details{margin-top:8px;}}"
        "</style>"
        "</head>"
        "<body>"
        '<main class="wrap">'
        '<header class="top"><div>'
        f'<p class="kicker">Day {day_number}/{total_days} · 约 {int(row["estimated_minutes"])} 分钟</p>'
        f"<h1>{escape(row['book_title'])}</h1>"
        f'<p class="meta">{escape(row["book_author"] or "未知作者")} · {escape(row["mode"])} · {escape(row["tone"])} · artifact: {escape(row["artifact_path"] or "")}</p>'
        f"</div>{spoiler_badge}</header>"
        f'<div class="progress" aria-label="计划进度"><span class="bar" style="width:{progress_width}%"></span></div>'
        f'<nav class="days" aria-label="阅读天数">{"".join(day_links)}</nav>'
        '<section class="hero">'
        "<h2>今日钩子</h2>"
        f"<p>{escape(content.get('hook', '今天只读这一小段。'))}</p>"
        '<div class="actions"><a class="button" href="#source">开始读这一小段</a><a class="button secondary" href="#explain">先看白话拆解</a></div>'
        "</section>"
        '<div class="grid"><article class="main">'
        f"{drama_panel}"
        '<section class="panel question">'
        "<h2>今天只抓一个问题</h2>"
        f"<p>{escape(content.get('one_question', '这段到底在解决什么问题？'))}</p>"
        "</section>"
        '<section id="source" class="panel source-box">'
        '<div class="source-head"><h2>今日原文</h2><details class="source-details"><summary>阅读提示</summary><p>先读完，不用记笔记。读不进去就回到导读。</p></details></div>'
        f'<div class="source-content">{source_paragraphs}</div>'
        "</section>"
        '<section id="explain" class="panel">'
        "<h2>白话拆解</h2>"
        f"<p>{escape(content.get('plain_explanation', ''))}</p>"
        "</section>"
        '<section class="panel">'
        "<h2>关键点</h2>"
        f"<ul>{key_points}</ul>"
        "</section>"
        '<section class="panel">'
        "<h2>现实连接</h2>"
        f"<p>{escape(content.get('reality_connection', ''))}</p>"
        "</section>"
        '<section class="panel">'
        "<h2>明天预告</h2>"
        f"<p>{escape(content.get('tomorrow_teaser', ''))}</p>"
        "</section>"
        '</article><aside class="side">'
        f"{feedback}"
        "</aside></div>"
        "</main>"
        "</body>"
        "</html>"
    )


def _guided_reading_feedback_panel(plan_day_id: int, token: str) -> str:
    buttons = [
        ("completed", "读完了", "primary"),
        ("continue", "想继续", ""),
        ("just_right", "刚刚好", ""),
        ("too_long", "太长了", ""),
        ("not_interested", "没兴趣", ""),
    ]
    button_html = "".join(
        f'<button class="{css}" type="submit" name="event_type" value="{event}">{label}</button>'
        for event, label, css in buttons
    )
    return (
        '<section class="feedback-card">'
        "<h2>今天的反馈</h2>"
        "<p>点一下就够。系统后续会用它调节明天的长度和口吻。</p>"
        '<form method="post" action="/guided-reading/feedback">'
        f'<input type="hidden" name="day_id" value="{plan_day_id}">'
        f'<input type="hidden" name="token" value="{escape(token, quote=True)}">'
        f'<textarea name="note" maxlength="{MAX_FREE_TEXT_LENGTH}" placeholder="可选：补一句哪里卡住了"></textarea>'
        f'<div class="feedback-buttons">{button_html}</div>'
        "</form>"
        "</section>"
    )


def _guided_reading_feedback_saved_page(return_url: str, event_type: str) -> str:
    labels = {
        "too_long": "太长了",
        "not_interested": "没兴趣",
        "just_right": "刚刚好",
        "continue": "想继续",
        "completed": "读完了",
    }
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>导读反馈已记录</title>"
        "<style>"
        ":root{--paper:#fffdf8;--canvas:#f1eee7;--ink:#24251f;--muted:#706d63;--line:#ddd5c8;--accent:#3f635c;}"
        "body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}"
        ".wrap{max-width:560px;margin:0 auto;padding:28px 18px;}h1{font-size:24px;margin:0 0 10px;}p{font-size:15px;line-height:1.65;color:var(--muted);}a{display:inline-block;margin-top:8px;padding:10px 12px;border:1px solid var(--line);border-radius:7px;background:var(--paper);color:var(--accent);text-decoration:none;}"
        "</style>"
        "</head>"
        "<body>"
        '<main class="wrap">'
        "<h1>导读反馈已记录</h1>"
        f"<p>这次反馈是：{escape(labels.get(event_type, event_type))}。</p>"
        f'<a href="{escape(return_url, quote=True)}">回到今日导读</a>'
        "</main>"
        "</body>"
        "</html>"
    )


def _guided_reading_plans_page(settings: Settings, plans, admin_token: str) -> str:
    rows = []
    for plan in plans:
        lark = "开" if int(plan["lark_push_enabled"] or 0) else "关"
        rows.append(
            "<tr>"
            f"<td>{int(plan['id'])}</td>"
            f"<td>{escape(plan['book_title'])}</td>"
            f"<td>{escape(plan['mode'])} / {escape(plan['tone'])}</td>"
            f"<td>{int(plan['plan_days'])} 天 · {int(plan['daily_minutes'])} 分钟</td>"
            f"<td>{lark}</td>"
            f"<td>{escape(plan['status'])}</td>"
            "</tr>"
        )
    table = "".join(rows) or '<tr><td colspan="6">暂无阅读计划</td></tr>'
    action = f"{settings.public_base_url.rstrip('/')}/guided-reading/plans"
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>导读计划配置</title>"
        "<style>"
        ":root{--paper:#fffdf8;--canvas:#f1eee7;--ink:#24251f;--muted:#706d63;--line:#ddd5c8;--accent:#3f635c;--accent-soft:#e3ece8;}"
        "*{box-sizing:border-box;}body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}.wrap{max-width:980px;margin:0 auto;padding:24px 16px 56px;}h1{margin:0 0 16px;font-size:28px;}.grid{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:18px;align-items:start;}.panel{padding:18px;border:1px solid var(--line);border-radius:8px;background:var(--paper);box-shadow:0 10px 28px rgba(69,57,37,.055);}h2{margin:0 0 12px;font-size:18px;}label{display:block;margin:12px 0 6px;color:var(--muted);font-size:13px;}input,textarea,select{width:100%;padding:10px;border:1px solid var(--line);border-radius:7px;background:#fffefb;color:var(--ink);font-size:14px;}textarea{min-height:220px;resize:vertical;line-height:1.55;}button{margin-top:14px;width:100%;min-height:42px;border:1px solid var(--accent);border-radius:7px;background:var(--accent);color:#fff;font-size:14px;}table{width:100%;border-collapse:collapse;font-size:14px;}th,td{padding:10px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;}th{color:var(--muted);font-weight:600;}.two{display:grid;grid-template-columns:1fr 1fr;gap:10px;}.check{display:flex;gap:8px;align-items:center;margin-top:12px;color:var(--ink);}.check input{width:auto;}@media(max-width:820px){.grid{display:block;}.panel{margin-bottom:16px;}.two{grid-template-columns:1fr;}table{display:block;overflow-x:auto;white-space:nowrap;}}"
        "</style>"
        "</head>"
        "<body>"
        '<main class="wrap">'
        "<h1>导读计划配置</h1>"
        f'<p><a href="{escape(settings.public_base_url.rstrip() + "/guided-reading/sources?" + urlencode({"admin_token": admin_token}), quote=True)}">进入书源管理</a></p>'
        '<div class="grid">'
        '<section class="panel"><h2>已有计划</h2><table><thead><tr><th>ID</th><th>书</th><th>模式</th><th>计划</th><th>飞书</th><th>状态</th></tr></thead><tbody>'
        f"{table}"
        "</tbody></table></section>"
        '<section class="panel"><h2>创建计划</h2>'
        f'<form method="post" action="{escape(action, quote=True)}">'
        f'<input type="hidden" name="admin_token" value="{escape(admin_token, quote=True)}">'
        '<label>书名</label><input name="title" required>'
        '<label>作者</label><input name="author">'
        '<div class="two"><div><label>计划天数</label><input name="plan_days" type="number" min="1" max="60" value="5"></div><div><label>每天分钟</label><input name="daily_minutes" type="number" min="1" max="180" value="8"></div></div>'
        '<div class="two"><div><label>模式</label><select name="mode"><option value="guided">渐进导读</option><option value="drama">追剧式</option><option value="fast_intro">轻速览</option><option value="deep_read">深读</option></select></div><div><label>口吻</label><select name="tone"><option value="short_video">短导读</option><option value="drama">追剧式</option><option value="coach">私教式</option><option value="deep">深读式</option></select></div></div>'
        '<label>剧透策略</label><select name="spoiler_policy"><option value="avoid">不剧透</option><option value="allow">允许剧透</option></select>'
        '<label class="check"><input type="checkbox" name="lark_push_enabled" value="1"> 飞书推送每日导读</label>'
        '<label>书源文本（Markdown / TXT）</label><textarea name="source_text" required></textarea>'
        "<button type=\"submit\">创建阅读计划</button>"
        "</form></section>"
        "</div>"
        "</main>"
        "</body>"
        "</html>"
    )


def _guided_reading_sources_page(settings: Settings, sources, admin_token: str) -> str:
    rows = []
    for source in sources:
        detail_url = f"{settings.public_base_url.rstrip()}/guided-reading/source?{urlencode({'id': int(source['id']), 'admin_token': admin_token})}"
        rows.append(
            "<tr>"
            f"<td>{int(source['id'])}</td>"
            f"<td><a href=\"{escape(detail_url, quote=True)}\">{escape(source['title'])}</a></td>"
            f"<td>{escape(source['original_filename'])}</td>"
            f"<td>{escape(source['file_format'])}</td>"
            f"<td>{int(source['char_count'])}</td>"
            f"<td>{escape(source['created_at'])}</td>"
            "</tr>"
        )
    table = "".join(rows) or '<tr><td colspan="6">暂无导入书源</td></tr>'
    action = f"{settings.public_base_url.rstrip()}/guided-reading/sources/upload"
    plans_url = f"{settings.public_base_url.rstrip()}/guided-reading/plans?{urlencode({'admin_token': admin_token})}"
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>书源管理</title>"
        "<style>"
        ":root{--paper:#fffdf8;--canvas:#f1eee7;--ink:#24251f;--muted:#706d63;--line:#ddd5c8;--accent:#3f635c;--accent-soft:#e3ece8;}*{box-sizing:border-box;}body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}.wrap{max-width:1040px;margin:0 auto;padding:24px 16px 56px;}h1{margin:0 0 10px;font-size:28px;}a{color:var(--accent);}.grid{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;align-items:start;}.panel{padding:18px;border:1px solid var(--line);border-radius:8px;background:var(--paper);box-shadow:0 10px 28px rgba(69,57,37,.055);}h2{margin:0 0 12px;font-size:18px;}label{display:block;margin:12px 0 6px;color:var(--muted);font-size:13px;}input{width:100%;padding:10px;border:1px solid var(--line);border-radius:7px;background:#fffefb;color:var(--ink);font-size:14px;}button{margin-top:14px;width:100%;min-height:42px;border:1px solid var(--accent);border-radius:7px;background:var(--accent);color:#fff;font-size:14px;}table{width:100%;border-collapse:collapse;font-size:14px;}th,td{padding:10px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;}th{color:var(--muted);font-weight:600;}.note{margin:0 0 16px;color:var(--muted);font-size:14px;line-height:1.6;}@media(max-width:820px){.grid{display:block;}.panel{margin-bottom:16px;}table{display:block;overflow-x:auto;white-space:nowrap;}}"
        "</style>"
        "</head>"
        "<body>"
        '<main class="wrap">'
        "<h1>书源管理</h1>"
        f'<p class="note"><a href="{escape(plans_url, quote=True)}">返回导读计划</a> · v1 支持 UTF-8 .md / .txt 和 .epub，单文件 10MB 以内。</p>'
        '<div class="grid">'
        '<section class="panel"><h2>已导入书源</h2><table><thead><tr><th>ID</th><th>书名</th><th>文件</th><th>格式</th><th>字数</th><th>导入时间</th></tr></thead><tbody>'
        f"{table}"
        "</tbody></table></section>"
        '<section class="panel"><h2>上传书源</h2>'
        f'<form method="post" action="{escape(action, quote=True)}" enctype="multipart/form-data">'
        f'<input type="hidden" name="admin_token" value="{escape(admin_token, quote=True)}">'
        '<label>书名</label><input name="title" required>'
        '<label>作者</label><input name="author">'
        '<label>文件</label><input name="source_file" type="file" accept=".md,.txt,.epub,text/plain,text/markdown,application/epub+zip" required>'
        "<button type=\"submit\">导入书源</button>"
        "</form></section>"
        "</div>"
        "</main>"
        "</body>"
        "</html>"
    )


def _guided_reading_source_detail_page(settings: Settings, row, preview: str, admin_token: str) -> str:
    create_action = f"{settings.public_base_url.rstrip()}/guided-reading/plans"
    delete_action = f"{settings.public_base_url.rstrip()}/guided-reading/sources/delete"
    sources_url = f"{settings.public_base_url.rstrip()}/guided-reading/sources?{urlencode({'admin_token': admin_token})}"
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(row['title'])} 书源</title>"
        "<style>"
        ":root{--paper:#fffdf8;--canvas:#f1eee7;--ink:#24251f;--muted:#706d63;--line:#ddd5c8;--accent:#3f635c;--danger:#8f5f58;}*{box-sizing:border-box;}body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}.wrap{max-width:980px;margin:0 auto;padding:24px 16px 56px;}h1{margin:0 0 8px;font-size:28px;}.meta{margin:0 0 16px;color:var(--muted);font-size:14px;line-height:1.6;}a{color:var(--accent);}.grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:18px;align-items:start;}.panel{padding:18px;border:1px solid var(--line);border-radius:8px;background:var(--paper);box-shadow:0 10px 28px rgba(69,57,37,.055);}pre{white-space:pre-wrap;word-break:break-word;margin:0;font-size:15px;line-height:1.72;}label{display:block;margin:12px 0 6px;color:var(--muted);font-size:13px;}input,select{width:100%;padding:10px;border:1px solid var(--line);border-radius:7px;background:#fffefb;color:var(--ink);font-size:14px;}button{margin-top:14px;width:100%;min-height:42px;border:1px solid var(--accent);border-radius:7px;background:var(--accent);color:#fff;font-size:14px;}.danger{border-color:var(--danger);background:#fff7f5;color:var(--danger);}@media(max-width:820px){.grid{display:block;}.panel{margin-bottom:16px;}}"
        "</style>"
        "</head>"
        "<body>"
        '<main class="wrap">'
        f"<h1>{escape(row['title'])}</h1>"
        f'<p class="meta"><a href="{escape(sources_url, quote=True)}">返回书源管理</a> · {escape(row["original_filename"])} · {escape(row["file_format"])} · {int(row["char_count"])} 字</p>'
        '<div class="grid">'
        f'<section class="panel"><h2>内容预览</h2><pre>{escape(preview)}</pre></section>'
        '<aside class="panel"><h2>基于此书源创建计划</h2>'
        f'<form method="post" action="{escape(create_action, quote=True)}">'
        f'<input type="hidden" name="admin_token" value="{escape(admin_token, quote=True)}">'
        f'<input type="hidden" name="source_file_id" value="{int(row["id"])}">'
        f'<input type="hidden" name="title" value="{escape(row["title"], quote=True)}">'
        f'<input type="hidden" name="author" value="{escape(row["author"] or "", quote=True)}">'
        '<label>计划天数</label><input name="plan_days" type="number" min="1" max="60" value="5">'
        '<label>每天分钟</label><input name="daily_minutes" type="number" min="1" max="180" value="8">'
        '<label>模式</label><select name="mode"><option value="guided">渐进导读</option><option value="drama">追剧式</option><option value="fast_intro">轻速览</option><option value="deep_read">深读</option></select>'
        '<label>口吻</label><select name="tone"><option value="short_video">短导读</option><option value="drama">追剧式</option><option value="coach">私教式</option><option value="deep">深读式</option></select>'
        '<label>剧透策略</label><select name="spoiler_policy"><option value="avoid">不剧透</option><option value="allow">允许剧透</option></select>'
        '<label><input type="checkbox" name="lark_push_enabled" value="1"> 飞书推送每日导读</label>'
        "<button type=\"submit\">创建阅读计划</button>"
        "</form>"
        f'<form method="post" action="{escape(delete_action, quote=True)}">'
        f'<input type="hidden" name="admin_token" value="{escape(admin_token, quote=True)}">'
        f'<input type="hidden" name="source_file_id" value="{int(row["id"])}">'
        '<button class="danger" type="submit">删除书源</button>'
        "</form>"
        "</aside></div>"
        "</main>"
        "</body>"
        "</html>"
    )


def _guided_reading_source_uploaded_page(detail_url: str, source_id: int) -> str:
    return _redirect_like_page("书源已导入", detail_url, f"查看书源 #{source_id}")


def _redirect_like_page(title: str, url: str, label: str) -> str:
    return (
        "<!doctype html>"
        '<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        "<style>:root{--paper:#fffdf8;--canvas:#f1eee7;--ink:#24251f;--muted:#706d63;--line:#ddd5c8;--accent:#3f635c;}body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}.wrap{max-width:560px;margin:0 auto;padding:28px 18px;}h1{font-size:24px;margin:0 0 10px;}a{display:inline-block;margin-top:8px;padding:10px 12px;border:1px solid var(--line);border-radius:7px;background:var(--paper);color:var(--accent);text-decoration:none;}</style>"
        "</head><body><main class=\"wrap\">"
        f"<h1>{escape(title)}</h1>"
        f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'
        "</main></body></html>"
    )


def _guided_reading_plan_created_page(first_day_url: str, plan_id: int) -> str:
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>阅读计划已创建</title>"
        "<style>"
        ":root{--paper:#fffdf8;--canvas:#f1eee7;--ink:#24251f;--muted:#706d63;--line:#ddd5c8;--accent:#3f635c;}body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--canvas);color:var(--ink);}.wrap{max-width:560px;margin:0 auto;padding:28px 18px;}h1{font-size:24px;margin:0 0 10px;}p{font-size:15px;line-height:1.65;color:var(--muted);}a{display:inline-block;margin-top:8px;padding:10px 12px;border:1px solid var(--line);border-radius:7px;background:var(--paper);color:var(--accent);text-decoration:none;}"
        "</style>"
        "</head>"
        "<body>"
        '<main class="wrap">'
        "<h1>阅读计划已创建</h1>"
        f"<p>plan_id={plan_id}。第一天导读已经生成。</p>"
        f'<a href="{escape(first_day_url, quote=True)}">打开第一天导读</a>'
        "</main>"
        "</body>"
        "</html>"
    )


def _verify_admin_token(token: str, secret: str) -> bool:
    return bool(token and secret and token == sign_feedback_free_text(0, secret))


def _parse_multipart_form(raw: bytes, content_type: str) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("multipart boundary missing")
    boundary = content_type.split(marker, 1)[1].split(";", 1)[0].strip().strip('"')
    if not boundary:
        raise ValueError("multipart boundary missing")
    delimiter = ("--" + boundary).encode("utf-8")
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for part in raw.split(delimiter):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_raw, body = part.split(b"\r\n\r\n", 1)
        body = body.rstrip(b"\r\n")
        headers = header_raw.decode("utf-8", errors="replace")
        disposition = ""
        for line in headers.splitlines():
            if line.lower().startswith("content-disposition:"):
                disposition = line
                break
        name = _multipart_attr(disposition, "name")
        filename = _multipart_attr(disposition, "filename")
        if not name:
            continue
        if filename:
            files[name] = (Path(filename).name, body)
        else:
            fields[name] = body.decode("utf-8", errors="replace")
    return fields, files


def _multipart_attr(disposition: str, key: str) -> str:
    pattern = f'{key}="'
    if pattern not in disposition:
        return ""
    start = disposition.find(pattern) + len(pattern)
    end = disposition.find('"', start)
    if end < 0:
        return ""
    return disposition[start:end]


def _text_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()] or [text.strip()]


def _section(title: str, raw) -> str:
    text = _text(raw)
    if not text:
        return ""
    return f"<section><h2>{escape(title)}</h2>{_paragraph_body(text)}</section>"


def _list_section(title: str, raw) -> str:
    items = _items(raw)
    if not items:
        return ""
    body = "".join(f"<li>{_list_item_body(item)}</li>" for item in items)
    return f"<section><h2>{escape(title)}</h2><ol>{body}</ol></section>"


def _walkthrough_section(raw) -> str:
    items = raw if isinstance(raw, list) else []
    if not items:
        return ""
    rows = []
    for item in items:
        if isinstance(item, dict):
            title = _text(item.get("title_or_inferred_title")) or "部分"
            text = "；".join(
                part
                for part in [
                    _text(item.get("what_happens")),
                    _text(item.get("key_claim")),
                    _text(item.get("what_user_should_absorb")),
                ]
                if part
            )
            parts = [
                ("内容", _text(item.get("what_happens"))),
                ("关键主张", _text(item.get("key_claim"))),
                ("吸收重点", _text(item.get("what_user_should_absorb"))),
            ]
            detail = _labeled_parts(parts) or _list_item_body(text)
            rows.append(f"<li><strong>{escape(title)}</strong>{detail}</li>")
        else:
            rows.append(f"<li>{_list_item_body(_text(item))}</li>")
    return f"<section><h2>章节/部分 Walkthrough</h2><ol>{''.join(rows)}</ol></section>"


def _concept_section(raw) -> str:
    items = raw if isinstance(raw, list) else []
    if not items:
        return ""
    rows = []
    for item in items:
        if isinstance(item, dict):
            concept = _text(item.get("concept")) or "概念"
            text = "；".join(
                part
                for part in [
                    _text(item.get("meaning")),
                    _text(item.get("why_it_matters")),
                    _text(item.get("how_to_recognize_it")),
                ]
                if part
            )
            parts = [
                ("含义", _text(item.get("meaning"))),
                ("重要性", _text(item.get("why_it_matters"))),
                ("识别方式", _text(item.get("how_to_recognize_it"))),
            ]
            detail = _labeled_parts(parts) or _list_item_body(text)
            rows.append(f"<li><strong>{escape(concept)}</strong>{detail}</li>")
        else:
            rows.append(f"<li>{_list_item_body(_text(item))}</li>")
    return f"<section><h2>核心概念卡</h2><ol>{''.join(rows)}</ol></section>"


def _items(raw) -> list[str]:
    if isinstance(raw, list):
        return [_text(item) for item in raw if _text(item)]
    text = _text(raw)
    return [text] if text else []


def _paragraph_body(text: str) -> str:
    paragraphs = _split_reading_paragraphs(text)
    return "".join(f'<p class="text-paragraph">{escape(paragraph)}</p>' for paragraph in paragraphs)


def _list_item_body(text: str) -> str:
    chunks = _split_reading_paragraphs(text, target=130, hard_limit=190)
    return "".join(f'<span class="li-part">{escape(chunk)}</span>' for chunk in chunks)


def _labeled_parts(parts: list[tuple[str, str]]) -> str:
    rows = []
    for label, text in parts:
        clean = _text(text)
        if not clean:
            continue
        for index, chunk in enumerate(_split_reading_paragraphs(clean, target=120, hard_limit=180)):
            prefix = f"<b>{escape(label)}：</b>" if index == 0 else ""
            rows.append(f'<span class="li-part">{prefix}{escape(chunk)}</span>')
    return "".join(rows)


def _split_reading_paragraphs(text: str, target: int = 180, hard_limit: int = 260) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []
    if len(clean) <= hard_limit:
        return [clean]
    segments = _sentence_segments(clean)
    paragraphs: list[str] = []
    current = ""
    for segment in segments:
        if not segment:
            continue
        if len(segment) > hard_limit:
            if current:
                paragraphs.append(current)
                current = ""
            paragraphs.extend(_hard_chunks(segment, hard_limit))
            continue
        if current and len(current) + len(segment) > target:
            paragraphs.append(current)
            current = segment
        else:
            current += segment
    if current:
        paragraphs.append(current)
    return paragraphs


def _sentence_segments(text: str) -> list[str]:
    segments = []
    current = ""
    for char in text:
        current += char
        if char in "。！？；;.!?":
            segments.append(current)
            current = ""
    if current:
        segments.append(current)
    return segments


def _hard_chunks(text: str, size: int) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


def _text(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict):
        return "；".join(f"{key}: {_text(value)}" for key, value in raw.items() if _text(value))
    if isinstance(raw, list):
        return "；".join(_text(item) for item in raw if _text(item))
    return " ".join(str(raw).split())


def _json_loads(raw: str, default):
    try:
        return json.loads(raw or "")
    except json.JSONDecodeError:
        return default
