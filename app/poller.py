from __future__ import annotations

import logging
import time
from pathlib import Path

from app.profile import process_feedback
from app.repository import Repository
from app.telegram import FEEDBACK_LABELS, TelegramClient, parse_feedback_updates

logger = logging.getLogger(__name__)


class TelegramPoller:
    def __init__(self, telegram: TelegramClient, repo: Repository, offset_path: Path):
        self.telegram = telegram
        self.repo = repo
        self.offset_path = offset_path

    def run_once(self) -> int:
        offset = self._read_offset()
        updates = self.telegram.get_updates(offset=offset)
        next_offset, callbacks = parse_feedback_updates(updates)
        if next_offset is not None:
            self._write_offset(next_offset)

        for callback in callbacks:
            self.repo.add_feedback(callback.recommendation_id, callback.feedback_type)
            label = FEEDBACK_LABELS[callback.feedback_type]
            self.telegram.answer_callback_query(callback.callback_query_id, f"已记录：{label}")

        processed = process_feedback(self.repo)
        logger.info("Telegram poll completed: callbacks=%s processed=%s", len(callbacks), processed)
        return len(callbacks)

    def run_forever(self, sleep_seconds: int = 2) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Telegram polling iteration failed")
                time.sleep(10)
            time.sleep(sleep_seconds)

    def _read_offset(self) -> int | None:
        if not self.offset_path.exists():
            return None
        raw = self.offset_path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None

    def _write_offset(self, offset: int) -> None:
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self.offset_path.write_text(str(offset), encoding="utf-8")

