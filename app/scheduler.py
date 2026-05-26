from __future__ import annotations

import logging
import time
from datetime import datetime

from app.config import Settings
from app.workflow import ReadingCoachWorkflow

logger = logging.getLogger(__name__)


class DailyScheduler:
    def __init__(self, settings: Settings, workflow: ReadingCoachWorkflow):
        self.settings = settings
        self.workflow = workflow
        self.last_daily_date: str | None = None
        self.last_weekly_date: str | None = None

    def run_forever(self) -> None:
        logger.info("Scheduler started: daily_push_time=%s", self.settings.daily_push_time)
        while True:
            self.tick()
            time.sleep(30)

    def tick(self) -> None:
        now = datetime.now(self.settings.timezone)
        today = now.date().isoformat()
        current_time = now.strftime("%H:%M")
        if current_time == self.settings.daily_push_time and self.last_daily_date != today:
            logger.info("Starting scheduled daily recommendation")
            self.workflow.run_daily_recommendations()
            self.last_daily_date = today

        if now.isoweekday() == 7 and current_time == "20:00" and self.last_weekly_date != today:
            logger.info("Starting scheduled weekly report")
            self.workflow.send_weekly_report()
            self.last_weekly_date = today

