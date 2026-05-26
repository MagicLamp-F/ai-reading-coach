from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from threading import Thread

from app.config import Settings
from app.db import connect, init_db
from app.factory import build_context
from app.logging_setup import configure_logging
from app.metrics import MetricsServer
from app.poller import TelegramPoller
from app.profile import seed_user_manual
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
    subparsers.add_parser("run-weekly-report", help="Send one weekly profile report")

    server = subparsers.add_parser("run-server", help="Run the feedback HTTP server")
    server.add_argument("--host", default="127.0.0.1", help="Host to bind")
    server.add_argument("--port", type=int, default=8000, help="Port to bind")

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

    context = build_context(settings)

    if args.command == "seed-profile":
        text = Path(args.file).read_text(encoding="utf-8")
        seed_user_manual(context.repo, text)
        print("Seeded profile from user manual")
        return

    if args.command == "run-daily":
        run_id = context.workflow.run_daily_recommendations()
        print(f"Daily recommendation run completed: run_id={run_id}")
        return

    if args.command == "run-weekly-report":
        context.workflow.send_weekly_report()
        print("Weekly report sent")
        return

    if args.command == "run-server":
        run_feedback_server(settings, host=args.host, port=args.port)
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

