from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from threading import Thread

from app.config import Settings
from app.db import connect, init_db
from app.factory import build_context
from app.feedback import build_guided_reading_day_url
from app.guided_reading import GuidedReadingError, GuidedReadingService
from app.logging_setup import configure_logging
from app.metrics import MetricsServer
from app.memory import hermes_profile_sync_status
from app.poller import TelegramPoller
from app.profile import seed_user_manual
from app.reading_pack import FastReadPackService
from app.reflection import (
    HermesReflectionService,
    ReflectionError,
    ensure_memory_layout,
    format_reflection_list,
    format_reflection_show,
)
from app.scheduler import DailyScheduler
from app.server import run_feedback_server

logger = logging.getLogger(__name__)


def main() -> None:
    _load_env_file(Path(".env"))
    parser = argparse.ArgumentParser(description="AI reading coach MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the SQLite database")

    seed = subparsers.add_parser("seed-profile", help="Seed profile items from a user manual text file")
    seed.add_argument("--file", required=True, help="Path to a UTF-8 text file")

    subparsers.add_parser("run-daily", help="Run one daily recommendation workflow")
    resend = subparsers.add_parser("resend-pending-deliveries", help="Retry pending delivery outbox messages")
    resend.add_argument("--limit", type=int, default=20, help="Maximum pending deliveries to retry")
    resend.add_argument("--max-attempts", type=int, default=5, help="Mark a delivery failed after this many retries")
    subparsers.add_parser("run-weekly-report", help="Send one weekly profile report")

    profile_sync = subparsers.add_parser("show-hermes-profile-sync", help="Show Hermes native profile sync status")
    profile_sync.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    profile_sync.add_argument("--preview-chars", type=int, default=700, help="Maximum synced entry preview chars")

    reading_pack = subparsers.add_parser("generate-reading-pack", help="Generate a deep read pack for a recommendation")
    reading_pack.add_argument("--recommendation-id", type=int, required=True, help="Recommendation id")
    reading_pack.add_argument("--library-dir", default="library", help="Directory for long-form reading artifacts")

    guided_plan = subparsers.add_parser("create-guided-reading-plan", help="Create a progressive guided reading plan from a Markdown/TXT source")
    guided_plan.add_argument("--source-file", required=True, help="Path to a UTF-8 Markdown/TXT source file")
    guided_plan.add_argument("--title", required=True, help="Book title")
    guided_plan.add_argument("--author", default="", help="Book author")
    guided_plan.add_argument("--days", type=int, default=5, help="Number of planned reading days")
    guided_plan.add_argument("--daily-minutes", type=int, default=8, help="Target daily reading minutes")
    guided_plan.add_argument(
        "--mode",
        choices=["guided", "fast_intro", "deep_read", "drama"],
        default="guided",
        help="Reading mode",
    )
    guided_plan.add_argument(
        "--tone",
        choices=["short_video", "coach", "deep", "drama"],
        default="short_video",
        help="Guide tone",
    )
    guided_plan.add_argument(
        "--spoiler-policy",
        choices=["avoid", "allow"],
        default="avoid",
        help="Spoiler policy for narrative reading",
    )
    guided_plan.add_argument("--library-dir", default="library", help="Directory for guided reading artifacts")
    guided_plan.add_argument("--lark-push", action="store_true", help="Enable Lark push for this reading plan")

    guided_push = subparsers.add_parser("send-guided-reading-pushes", help="Send due guided reading days to Lark")
    guided_push.add_argument("--limit", type=int, default=10, help="Maximum guided reading day cards to send")

    reflection_generate = subparsers.add_parser("generate-reflection", help="Generate a Hermes reflection draft")
    reflection_generate.add_argument("--days", type=int, default=7, help="Number of recent days to reflect on")
    reflection_generate.add_argument(
        "--no-lark",
        action="store_true",
        help="Do not send the pending-review Lark summary after generation",
    )
    reflection_generate.add_argument(
        "--auto-apply",
        action="store_true",
        help="Automatically approve and apply the generated reflection, writing an audit change log",
    )
    reflection_generate.add_argument(
        "--no-auto-apply",
        action="store_true",
        help="Disable auto-apply even when HERMES_REFLECTION_AUTO_APPLY=true",
    )

    reflection_approve = subparsers.add_parser("approve-reflection", help="Approve a Hermes reflection draft")
    reflection_approve.add_argument("--id", type=int, required=True, help="Reflection id")

    reflection_apply = subparsers.add_parser("apply-reflection", help="Apply an approved Hermes reflection")
    reflection_apply.add_argument("--id", type=int, required=True, help="Reflection id")

    reflection_show = subparsers.add_parser("show-reflection", help="Show one Hermes reflection")
    reflection_show.add_argument("--id", type=int, required=True, help="Reflection id")

    subparsers.add_parser("list-reflections", help="List Hermes reflections")

    server = subparsers.add_parser("run-server", help="Run the feedback HTTP server")
    server.add_argument("--host", default="127.0.0.1", help="Host to bind")
    server.add_argument("--port", type=int, default=8000, help="Port to bind")

    api = subparsers.add_parser("run-api", help="Run the split frontend/backend JSON API")
    api.add_argument("--host", default="127.0.0.1", help="Host to bind")
    api.add_argument("--port", type=int, default=8000, help="Port to bind")

    poll = subparsers.add_parser("poll-telegram", help="Poll Telegram callback updates")
    poll.add_argument("--once", action="store_true", help="Run one poll iteration and exit")

    scheduler = subparsers.add_parser("run-scheduler", help="Run scheduler, metrics, and Telegram poller")
    scheduler.add_argument("--no-poller", action="store_true", help="Disable Telegram feedback polling")
    scheduler.add_argument("--metrics-port", type=int, default=9108, help="Prometheus metrics port")

    args = parser.parse_args()
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    if args.command == "init-db":
        conn = connect(settings.database_path)
        init_db(conn)
        print(f"Initialized database: {settings.database_path}")
        return

    if args.command == "show-hermes-profile-sync":
        status = hermes_profile_sync_status(
            snapshot_path=settings.hermes_native_profile_path,
            native_user_memory_path=settings.hermes_native_user_memory_path,
            preview_chars=args.preview_chars,
        )
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            print(format_hermes_profile_sync_status(status))
        return

    context = build_context(settings)

    if args.command == "seed-profile":
        text = Path(args.file).read_text(encoding="utf-8")
        seed_user_manual(context.repo, text)
        print("Seeded profile from user manual")
        return

    if args.command == "run-daily":
        run_id = context.workflow.run_daily_recommendations()
        if settings.daily_reflection_enabled:
            _run_daily_reflection(context, settings, run_id)
        print(f"Daily recommendation run completed: run_id={run_id}")
        return

    if args.command == "resend-pending-deliveries":
        sent = context.workflow.resend_pending_deliveries(limit=args.limit, max_attempts=args.max_attempts)
        print(f"Pending deliveries retried: sent={sent}")
        return

    if args.command == "run-weekly-report":
        context.workflow.send_weekly_report()
        print("Weekly report sent")
        return

    if args.command == "generate-reading-pack":
        service = FastReadPackService(
            repo=context.repo,
            llm=context.workflow.llm,
            memory_dir=context.workflow.memory_dir,
            library_dir=Path(args.library_dir),
            max_memory_chars=context.workflow.max_memory_chars,
            agent=context.reading_pack_agent,
            source_collector=context.source_collector,
        )
        result = service.generate_for_recommendation(args.recommendation_id)
        print(f"Deep read pack generated: id={result.reading_pack_id}")
        print(f"Status: {result.status}")
        print(f"Artifact: {result.artifact_path}")
        return

    if args.command == "create-guided-reading-plan":
        try:
            result = GuidedReadingService(context.repo, library_dir=Path(args.library_dir)).create_plan_from_source(
                source_path=Path(args.source_file),
                title=args.title,
                author=args.author,
                plan_days=args.days,
                daily_minutes=args.daily_minutes,
                mode=args.mode,
                tone=args.tone,
                spoiler_policy=args.spoiler_policy,
                lark_push_enabled=args.lark_push,
            )
        except GuidedReadingError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Guided reading plan created: plan_id={result.plan_id}")
        print(f"Days: {len(result.day_ids)}")
        print(f"First day id: {result.first_day_id}")
        if settings.feedback_secret:
            url = build_guided_reading_day_url(settings.public_base_url, result.first_day_id, settings.feedback_secret)
            print(f"First day: {url}")
        else:
            print("First day URL unavailable: FEEDBACK_SECRET is not configured")
        return

    if args.command == "send-guided-reading-pushes":
        sent = 0
        for row in context.repo.next_lark_push_reading_days(limit=args.limit):
            url = build_guided_reading_day_url(settings.public_base_url, int(row["id"]), settings.feedback_secret)
            message_id = context.lark.send_guided_reading_day(row, url)
            if message_id is not None or not context.lark.enabled():
                event_type = "lark_push_sent" if message_id else "lark_push_skipped_disabled"
                context.repo.add_reading_progress_event(
                    int(row["plan_id"]),
                    int(row["id"]),
                    event_type,
                    {"message_id": message_id or ""},
                )
                sent += 1
            else:
                context.repo.add_reading_progress_event(
                    int(row["plan_id"]),
                    int(row["id"]),
                    "lark_push_failed",
                    {"error": getattr(context.lark, "last_send_error", "")},
                )
        print(f"Guided reading pushes processed: sent={sent}")
        return

    if args.command == "generate-reflection":
        auto_apply = settings.hermes_reflection_auto_apply
        if args.auto_apply:
            auto_apply = True
        if args.no_auto_apply:
            auto_apply = False
        service = HermesReflectionService(
            repo=context.repo,
            llm=context.workflow.llm,
            weekly_report_builder=context.workflow.build_weekly_report,
            lark=context.lark,
            adapter=context.reflection_adapter,
        )
        reflection_id = service.generate_reflection(days=args.days, notify_lark=not args.no_lark, auto_apply=auto_apply)
        print(f"Hermes reflection draft generated: id={reflection_id}")
        if auto_apply:
            print("Status: applied automatically; audit log written under memory/change_logs.")
        else:
            print("Status: draft; pending approval before apply.")
        return

    if args.command == "approve-reflection":
        _reflection_service(context).approve_reflection(args.id)
        print(f"Approved reflection: id={args.id}")
        return

    if args.command == "apply-reflection":
        _reflection_service(context).apply_reflection(args.id)
        print(f"Applied reflection: id={args.id}")
        return

    if args.command == "show-reflection":
        row = context.repo.get_reflection(args.id)
        if row is None:
            raise ReflectionError(f"Reflection not found: id={args.id}")
        print(format_reflection_show(row))
        return

    if args.command == "list-reflections":
        ensure_memory_layout()
        print(format_reflection_list(context.repo.list_reflections()))
        return

    if args.command == "run-server":
        run_feedback_server(settings, host=args.host, port=args.port)
        return

    if args.command == "run-api":
        import uvicorn

        from app.api.main import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return

    if args.command == "poll-telegram":
        poller = TelegramPoller(context.telegram, context.repo, Path("data/telegram_offset.txt"))
        if args.once:
            callbacks = poller.run_once()
            print(f"Processed callback updates: {callbacks}")
        else:
            poller.run_forever()
        return

    if args.command == "run-scheduler":
        MetricsServer(context.repo, port=args.metrics_port).start_background()
        logger.info("Metrics server started on port %s", args.metrics_port)
        if not args.no_poller:
            poller = TelegramPoller(context.telegram, context.repo, Path("data/telegram_offset.txt"))
            Thread(target=poller.run_forever, daemon=True).start()
            logger.info("Telegram poller started")
        DailyScheduler(settings, context.workflow).run_forever()


def _reflection_service(context) -> HermesReflectionService:
    return HermesReflectionService(
        repo=context.repo,
        llm=context.workflow.llm,
        weekly_report_builder=context.workflow.build_weekly_report,
        lark=context.lark,
        adapter=context.reflection_adapter,
    )


def _run_daily_reflection(context, settings: Settings, daily_run_id: int) -> None:
    try:
        reflection_id = _reflection_service(context).generate_reflection(
            days=settings.daily_reflection_days,
            notify_lark=True,
            auto_apply=settings.hermes_reflection_auto_apply,
        )
    except Exception as exc:
        warning = f"daily reflection failed after run_id={daily_run_id}: {exc}"
        logger.warning(warning)
        context.repo.record_run_warning(daily_run_id, warning)
        return

    mode = "auto-applied" if settings.hermes_reflection_auto_apply else "draft"
    logger.info("Daily reflection completed after run_id=%s: reflection_id=%s mode=%s", daily_run_id, reflection_id, mode)


def format_hermes_profile_sync_status(status: dict[str, object]) -> str:
    lines = [
        "Hermes profile sync status",
        f"- snapshot_path: {status['snapshot_path']}",
        f"- snapshot_exists: {status['snapshot_exists']}",
        f"- snapshot_chars: {status['snapshot_chars']}",
        f"- snapshot_mtime: {status['snapshot_mtime'] or '(missing)'}",
        f"- native_user_memory_path: {status['native_user_memory_path'] or '(disabled)'}",
        f"- native_user_memory_enabled: {status['native_user_memory_enabled']}",
        f"- native_user_memory_exists: {status['native_user_memory_exists']}",
        f"- native_user_memory_chars: {status['native_user_memory_chars']}",
        f"- native_user_memory_mtime: {status['native_user_memory_mtime'] or '(missing)'}",
        f"- arc_entry_present: {status['arc_entry_present']}",
        f"- arc_entry_chars: {status['arc_entry_chars']}",
    ]
    preview = str(status.get("arc_entry_preview") or "")
    if preview:
        lines.extend(["", "arc_entry_preview:", preview])
    return "\n".join(lines)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    main()
