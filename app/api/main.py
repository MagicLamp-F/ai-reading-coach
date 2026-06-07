from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.api.serializers import (
    created_plan_payload,
    guided_day_payload,
    reading_pack_payload,
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
from app.repository import Repository
from app.server import MAX_FREE_TEXT_LENGTH

logger = logging.getLogger(__name__)


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
    def list_reading_plans(admin_token: str, repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
        _require_admin(admin_token, settings)
        return {"plans": [reading_plan_payload(row) for row in repo.list_reading_plans()]}

    @app.get("/api/admin/reading-plans/{plan_id}")
    def get_reading_plan(plan_id: int, admin_token: str, repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
        _require_admin(admin_token, settings)
        row = repo.get_reading_plan_detail(plan_id)
        if row is None:
            raise HTTPException(status_code=404, detail="阅读计划不存在")
        return reading_plan_payload(row, repo.reading_plan_days(plan_id))

    @app.post("/api/admin/reading-plans")
    def create_reading_plan(payload: dict, repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
        _require_admin(str(payload.get("admin_token") or ""), settings)
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
    def list_reading_sources(admin_token: str, repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
        _require_admin(admin_token, settings)
        return {"sources": [source_file_payload(row) for row in repo.list_reading_source_files()]}

    @app.get("/api/admin/reading-sources/{source_id}")
    def get_reading_source(source_id: int, admin_token: str, repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
        _require_admin(admin_token, settings)
        row = repo.get_reading_source_file(source_id)
        if row is None or row["status"] != "active":
            raise HTTPException(status_code=404, detail="书源不存在")
        return source_file_payload(row, include_preview=True)

    @app.post("/api/admin/reading-sources/upload")
    async def upload_reading_source(
        admin_token: Annotated[str, Form()],
        title: Annotated[str, Form()],
        author: Annotated[str, Form()] = "",
        source_file: UploadFile = File(),
        repo: Repository = Depends(get_repo),
        settings: Settings = Depends(get_settings),
    ):
        _require_admin(admin_token, settings)
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
    def delete_reading_source(source_id: int, payload: dict, repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
        _require_admin(str(payload.get("admin_token") or ""), settings)
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


def _require_admin(admin_token: str, settings: Settings) -> None:
    if not verify_guided_reading_day_signature(0, admin_token, settings.feedback_secret):
        from app.feedback import verify_feedback_free_text_signature

        if not verify_feedback_free_text_signature(0, admin_token, settings.feedback_secret):
            raise HTTPException(status_code=403, detail="签名无效")


app = create_app()
