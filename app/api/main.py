from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.api.serializers import (
    created_plan_payload,
    guided_day_payload,
    reading_pack_payload,
    reading_quote_payload,
    reading_plan_payload,
    source_file_payload,
)
from app.config import Settings
from app.db import connect, init_db
from app.feedback import (
    FEEDBACK_REASONS,
    FEEDBACK_TYPES,
    sign_guided_reading_day,
    verify_feedback_signature,
    verify_guided_reading_day_signature,
    verify_reading_pack_signature,
)
from app.guided_reading import GuidedReadingError, GuidedReadingService
from app.repository import ProfileItemReviewDraft, ReadingQuoteDraft, Repository
from app.server import MAX_FREE_TEXT_LENGTH, MAX_QUOTE_TEXT_LENGTH, _record_quote_profile_signal
from app.workflow import build_weekly_report_payload

logger = logging.getLogger(__name__)

ADMIN_SESSION_COOKIE = "arc_admin_session"
ADMIN_SESSION_TTL_SECONDS = 60 * 60 * 24 * 7


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    app = FastAPI(title="AI Reading Coach API", version="0.1.0")
    app.state.settings = app_settings
    app.state.http_requests_total: dict[tuple[str, str, int], int] = {}
    app.state.http_request_duration_sum: dict[tuple[str, str], float] = {}
    app.state.http_request_duration_count: dict[tuple[str, str], int] = {}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            path_template = getattr(route, "path", request.url.path)
            method = request.method
            elapsed = time.perf_counter() - started
            total_key = (method, path_template, status_code)
            app.state.http_requests_total[total_key] = app.state.http_requests_total.get(total_key, 0) + 1
            duration_key = (method, path_template)
            app.state.http_request_duration_sum[duration_key] = app.state.http_request_duration_sum.get(duration_key, 0.0) + elapsed
            app.state.http_request_duration_count[duration_key] = app.state.http_request_duration_count.get(duration_key, 0) + 1
            if status_code >= 500:
                logger.error("api_request_failed method=%s path=%s status=%s elapsed=%.4f", method, path_template, status_code, elapsed)

    @app.get("/healthz")
    @app.get("/api/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/metrics", response_class=PlainTextResponse)
    def metrics(request: Request) -> str:
        lines = [
            "# HELP arc_api_requests_total API requests by method, path, and status.",
            "# TYPE arc_api_requests_total counter",
        ]
        for (method, path, status), count in sorted(request.app.state.http_requests_total.items()):
            lines.append(f'arc_api_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}')
        lines.extend(
            [
                "# HELP arc_api_request_duration_seconds_sum API request duration sum.",
                "# TYPE arc_api_request_duration_seconds_sum counter",
            ]
        )
        for (method, path), value in sorted(request.app.state.http_request_duration_sum.items()):
            lines.append(f'arc_api_request_duration_seconds_sum{{method="{method}",path="{path}"}} {value:.6f}')
        lines.extend(
            [
                "# HELP arc_api_request_duration_seconds_count API request duration count.",
                "# TYPE arc_api_request_duration_seconds_count counter",
            ]
        )
        for (method, path), value in sorted(request.app.state.http_request_duration_count.items()):
            lines.append(f'arc_api_request_duration_seconds_count{{method="{method}",path="{path}"}} {value}')
        return "\n".join(lines) + "\n"

    @app.get("/api/admin/session")
    def admin_session(request: Request, settings: Settings = Depends(get_settings)):
        _require_admin(request, "", settings)
        return {"authenticated": True, "username": getattr(settings, "admin_username", "admin")}

    @app.post("/api/admin/login")
    def admin_login(payload: dict, response: Response, settings: Settings = Depends(get_settings)):
        username = str(payload.get("username") or "")
        password = str(payload.get("password") or "")
        expected_username = getattr(settings, "admin_username", "admin")
        expected_password = getattr(settings, "admin_password", "123456")
        if not hmac.compare_digest(username, expected_username) or not hmac.compare_digest(password, expected_password):
            raise HTTPException(status_code=403, detail="账号或密码错误")
        token = _sign_admin_session(username, settings.feedback_secret, int(time.time()) + ADMIN_SESSION_TTL_SECONDS)
        response.set_cookie(
            ADMIN_SESSION_COOKIE,
            token,
            max_age=ADMIN_SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
        )
        return {"authenticated": True, "username": username}

    @app.post("/api/admin/logout")
    def admin_logout(response: Response):
        response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
        return {"authenticated": False}

    @app.get("/api/admin/weekly-report")
    def weekly_report(
        request: Request,
        days: int = 7,
        admin_token: str = "",
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, admin_token, settings)
        return build_weekly_report_payload(repo, days=days)

    @app.get("/api/admin/profile-evidence")
    def profile_evidence(
        request: Request,
        limit: int = 80,
        admin_token: str = "",
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, admin_token, settings)
        bounded_limit = max(1, min(int(limit), 200))
        rows = repo.profile_items_with_review_summary(limit=bounded_limit)
        return {"items": [_profile_evidence_payload(repo, row) for row in rows]}

    @app.get("/api/admin/reading-quotes")
    def reading_quotes(
        request: Request,
        limit: int = 80,
        admin_token: str = "",
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, admin_token, settings)
        bounded_limit = max(1, min(int(limit), 200))
        return {"items": [reading_quote_payload(row) for row in repo.recent_reading_quotes(limit=bounded_limit)]}

    @app.post("/api/admin/profile-evidence/{profile_item_id}/review")
    def review_profile_evidence(
        request: Request,
        profile_item_id: int,
        payload: dict,
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, str(payload.get("admin_token") or ""), settings)
        action = str(payload.get("action") or "").strip()
        note = str(payload.get("note") or "").strip()[:500]
        if action not in {"confirm", "inaccurate", "downrank"}:
            raise HTTPException(status_code=400, detail="画像纠偏动作无效")
        try:
            _, event = repo.review_profile_item(ProfileItemReviewDraft(profile_item_id=profile_item_id, action=action, note=note))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="画像条目不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row = repo.profile_item_with_review_summary(profile_item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="画像条目不存在")
        return {"item": _profile_evidence_payload(repo, row), "event": _profile_review_event_payload(event)}

    @app.get("/api/reading-packs/{reading_pack_id}")
    def get_reading_pack(reading_pack_id: int, token: str, module: str = "overview", repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
        if not verify_reading_pack_signature(reading_pack_id, token, settings.feedback_secret):
            raise HTTPException(status_code=403, detail="签名无效")
        row = repo.get_reading_pack_page(reading_pack_id)
        if row is None:
            raise HTTPException(status_code=404, detail="快读包不存在")
        return reading_pack_payload(row, token, module, settings.feedback_secret)

    @app.post("/api/reading-packs/{reading_pack_id}/feedback")
    def submit_reading_pack_feedback(
        reading_pack_id: int,
        payload: dict,
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        row = repo.get_reading_pack_page(reading_pack_id)
        if row is None:
            raise HTTPException(status_code=404, detail="快读包不存在")
        recommendation_id = int(row["recommendation_id"])
        feedback_type = str(payload.get("feedback_type") or "")
        reason_code = str(payload.get("reason_code") or "")
        token = str(payload.get("token") or "")
        if feedback_type not in FEEDBACK_TYPES or reason_code not in FEEDBACK_REASONS.get(feedback_type, []):
            raise HTTPException(status_code=400, detail="反馈类型无效")
        if not verify_feedback_signature(recommendation_id, feedback_type, token, settings.feedback_secret, reason_code):
            raise HTTPException(status_code=403, detail="签名无效")
        free_text = str(payload.get("free_text") or "").strip()[:MAX_FREE_TEXT_LENGTH]
        feedback_id = repo.add_feedback(recommendation_id, feedback_type, reason_code=reason_code, free_text=free_text)
        return {"status": "saved", "feedback_id": feedback_id}

    @app.get("/api/reading-packs/{reading_pack_id}/quotes")
    def list_reading_pack_quotes(reading_pack_id: int, token: str, repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
        if not verify_reading_pack_signature(reading_pack_id, token, settings.feedback_secret):
            raise HTTPException(status_code=403, detail="签名无效")
        row = repo.get_reading_pack_page(reading_pack_id)
        if row is None:
            raise HTTPException(status_code=404, detail="快读包不存在")
        return {"items": [reading_quote_payload(item) for item in repo.reading_quotes_for_pack(reading_pack_id, limit=50)]}

    @app.post("/api/reading-packs/{reading_pack_id}/quotes")
    def save_reading_pack_quote(
        reading_pack_id: int,
        payload: dict,
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        token = str(payload.get("token") or "")
        if not verify_reading_pack_signature(reading_pack_id, token, settings.feedback_secret):
            raise HTTPException(status_code=403, detail="签名无效")
        row = repo.get_reading_pack_page(reading_pack_id)
        if row is None:
            raise HTTPException(status_code=404, detail="快读包不存在")
        selected_text = " ".join(str(payload.get("selected_text") or "").split())[:MAX_QUOTE_TEXT_LENGTH]
        if not selected_text:
            raise HTTPException(status_code=400, detail="摘抄内容不能为空")
        note = str(payload.get("note") or "").strip()[:MAX_FREE_TEXT_LENGTH]
        quote_id = repo.add_reading_quote(
            ReadingQuoteDraft(
                reading_pack_id=reading_pack_id,
                recommendation_id=int(row["recommendation_id"]),
                book_id=int(row["book_id"]),
                selected_text=selected_text,
                note=note,
                module=str(payload.get("module") or "").strip()[:80],
                section_title=str(payload.get("section_title") or "").strip()[:160],
                metadata={"surface": "react_page", "book": row["book_title"]},
            )
        )
        _record_quote_profile_signal(repo, row, selected_text, note, quote_id)
        quote = repo.reading_quotes_for_pack(reading_pack_id, limit=1)[0]
        return {"status": "saved", "quote": reading_quote_payload(quote)}

    @app.get("/api/guided-reading/days/{day_id}")
    def get_guided_reading_day(day_id: int, token: str, repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
        if not verify_guided_reading_day_signature(day_id, token, settings.feedback_secret):
            raise HTTPException(status_code=403, detail="签名无效")
        row = repo.get_guided_reading_day_page(day_id)
        if row is None:
            raise HTTPException(status_code=404, detail="导读不存在")
        days = repo.reading_plan_days(int(row["plan_id"]))
        repo.add_reading_progress_event(int(row["plan_id"]), day_id, "opened", {"day_number": int(row["day_number"]), "surface": "api"})
        return guided_day_payload(row, days, token, settings.feedback_secret)

    @app.post("/api/guided-reading/days/{day_id}/feedback")
    def submit_guided_reading_feedback(day_id: int, payload: dict, repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
        token = str(payload.get("token") or "")
        event_type = str(payload.get("event_type") or "")
        note = str(payload.get("note") or "").strip()[:MAX_FREE_TEXT_LENGTH]
        if event_type not in {"too_long", "not_interested", "just_right", "continue", "completed"}:
            raise HTTPException(status_code=400, detail="反馈类型无效")
        if not verify_guided_reading_day_signature(day_id, token, settings.feedback_secret):
            raise HTTPException(status_code=403, detail="签名无效")
        row = repo.get_guided_reading_day_page(day_id)
        if row is None:
            raise HTTPException(status_code=404, detail="导读不存在")
        if event_type == "completed":
            repo.mark_reading_plan_day_completed(day_id)
        repo.add_reading_progress_event(
            int(row["plan_id"]),
            day_id,
            event_type,
            {"note": note, "day_number": int(row["day_number"]), "surface": "api"},
        )
        return {"status": "saved", "event_type": event_type}

    @app.get("/api/admin/reading-plans")
    def list_reading_plans(
        request: Request,
        admin_token: str = "",
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, admin_token, settings)
        return {"plans": [reading_plan_payload(row) for row in repo.list_reading_plans()]}

    @app.get("/api/admin/reading-plans/{plan_id}")
    def get_reading_plan(
        request: Request,
        plan_id: int,
        admin_token: str = "",
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, admin_token, settings)
        row = repo.get_reading_plan_detail(plan_id)
        if row is None:
            raise HTTPException(status_code=404, detail="阅读计划不存在")
        return reading_plan_payload(row, repo.reading_plan_days(plan_id))

    @app.post("/api/admin/reading-plans")
    def create_reading_plan(
        request: Request,
        payload: dict,
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, str(payload.get("admin_token") or ""), settings)
        service = GuidedReadingService(repo, library_dir=settings.reading_pack_library_dir)
        try:
            source_file_id = payload.get("source_file_id")
            if source_file_id:
                result = service.create_plan_from_source_file(
                    source_file_id=int(source_file_id),
                    plan_days=int(payload.get("plan_days") or 5),
                    daily_minutes=int(payload.get("daily_minutes") or 8),
                    mode=str(payload.get("mode") or "guided"),
                    tone=str(payload.get("tone") or "short_video"),
                    spoiler_policy=str(payload.get("spoiler_policy") or "avoid"),
                    lark_push_enabled=bool(payload.get("lark_push_enabled")),
                )
            else:
                result = service.create_plan_from_text(
                    source_text=str(payload.get("source_text") or ""),
                    title=str(payload.get("title") or "").strip(),
                    author=str(payload.get("author") or "").strip(),
                    plan_days=int(payload.get("plan_days") or 5),
                    daily_minutes=int(payload.get("daily_minutes") or 8),
                    mode=str(payload.get("mode") or "guided"),
                    tone=str(payload.get("tone") or "short_video"),
                    spoiler_policy=str(payload.get("spoiler_policy") or "avoid"),
                    lark_push_enabled=bool(payload.get("lark_push_enabled")),
                )
        except (GuidedReadingError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return created_plan_payload(result.plan_id, result.first_day_id, sign_guided_reading_day(result.first_day_id, settings.feedback_secret))

    @app.get("/api/admin/reading-sources")
    def list_reading_sources(
        request: Request,
        admin_token: str = "",
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, admin_token, settings)
        return {"sources": [source_file_payload(row) for row in repo.list_reading_source_files()]}

    @app.get("/api/admin/reading-sources/{source_id}")
    def get_reading_source(
        request: Request,
        source_id: int,
        admin_token: str = "",
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, admin_token, settings)
        row = repo.get_reading_source_file(source_id)
        if row is None or row["status"] != "active":
            raise HTTPException(status_code=404, detail="书源不存在")
        return source_file_payload(row, include_preview=True)

    @app.post("/api/admin/reading-sources/upload")
    async def upload_reading_source(
        request: Request,
        title: Annotated[str, Form()],
        admin_token: Annotated[str, Form()] = "",
        author: Annotated[str, Form()] = "",
        source_file: UploadFile = File(),
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, admin_token, settings)
        filename = source_file.filename or "source.txt"
        suffix = Path(filename).suffix.lower()
        if suffix not in {".md", ".txt", ".epub"}:
            raise HTTPException(status_code=400, detail="v1 只支持 .md / .txt / .epub")
        raw = await source_file.read()
        if len(raw) <= 0 or len(raw) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="上传过大，v1 限制 10MB 文件")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            source_id = GuidedReadingService(repo, library_dir=settings.reading_pack_library_dir).import_source_file(
                tmp_path,
                title=title.strip(),
                author=author.strip(),
                original_filename=filename,
            )
        except GuidedReadingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return {"status": "saved", "source_id": source_id}

    @app.delete("/api/admin/reading-sources/{source_id}")
    def delete_reading_source(
        request: Request,
        source_id: int,
        payload: dict,
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(request, str(payload.get("admin_token") or ""), settings)
        if not repo.mark_reading_source_file_deleted(source_id):
            raise HTTPException(status_code=404, detail="书源不存在")
        return {"status": "deleted", "source_id": source_id}

    return app


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_repo(settings: Settings = Depends(get_settings)):
    conn = connect(settings.database_path)
    init_db(conn)
    try:
        yield Repository(conn)
    finally:
        conn.close()


def _require_admin(request: Request, admin_token: str, settings: Settings) -> None:
    if _verify_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE, ""), settings.feedback_secret):
        return
    if not verify_guided_reading_day_signature(0, admin_token, settings.feedback_secret):
        from app.feedback import verify_feedback_free_text_signature

        if not verify_feedback_free_text_signature(0, admin_token, settings.feedback_secret):
            raise HTTPException(status_code=403, detail="签名无效")


def _sign_admin_session(username: str, secret: str, expires_at: int) -> str:
    if not secret:
        raise HTTPException(status_code=500, detail="FEEDBACK_SECRET 未配置")
    message = f"admin_session:{username}:{expires_at}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    payload = f"{username}:{expires_at}:{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _verify_admin_session(token: str, secret: str) -> bool:
    if not token or not secret:
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        username, expires_raw, signature = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").split(":", 2)
        expires_at = int(expires_raw)
    except (ValueError, UnicodeDecodeError):
        return False
    if expires_at < int(time.time()):
        return False
    expected = _sign_admin_session(username, secret, expires_at)
    return hmac.compare_digest(expected, token)


def _profile_evidence_payload(repo: Repository, row) -> dict:
    return {
        "id": int(row["id"]),
        "category": row["category"],
        "content": row["content"],
        "weight": float(row["weight"]),
        "confidence": float(row["confidence"]),
        "evidence_count": int(row["evidence_count"]),
        "evidence": _safe_json_list(row["evidence_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_seen_at": row["last_seen_at"],
        "review_count": int(row["review_count"]),
        "confirm_count": int(row["confirm_count"]),
        "inaccurate_count": int(row["inaccurate_count"]),
        "downrank_count": int(row["downrank_count"]),
        "latest_review": {
            "action": row["latest_review_action"],
            "note": row["latest_review_note"] or "",
            "created_at": row["latest_review_at"],
        }
        if row["latest_review_action"]
        else None,
        "reviews": [_profile_review_event_payload(event) for event in repo.profile_item_review_events(int(row["id"]), limit=5)],
    }


def _profile_review_event_payload(row) -> dict:
    return {
        "id": int(row["id"]),
        "profile_item_id": int(row["profile_item_id"]),
        "action": row["action"],
        "note": row["note"],
        "previous_weight": float(row["previous_weight"]),
        "previous_confidence": float(row["previous_confidence"]),
        "new_weight": float(row["new_weight"]),
        "new_confidence": float(row["new_confidence"]),
        "created_at": row["created_at"],
    }


def _safe_json_list(value: str) -> list:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


app = create_app()
