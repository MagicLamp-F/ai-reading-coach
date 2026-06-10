from __future__ import annotations

import json
import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.memory import read_hermes_user_memory_entry, upsert_hermes_user_memory_entry
from app.repository import HermesQuoteProfileUpdateEventDraft, Repository

logger = logging.getLogger(__name__)


class HermesQuoteIngestError(RuntimeError):
    pass


@dataclass(frozen=True)
class HermesQuoteIngestResult:
    status: str
    should_update_native_memory: bool
    native_memory_path: str
    memory_entry: str
    rationale: str
    confidence: float
    evidence_summary: str
    preference_summary: dict[str, Any]
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class QuoteIngestSummary:
    quote_count: int
    status: str
    event_id: int | None


class HermesQuoteProfileIngestor:
    name = "hermes-agent"

    def __init__(
        self,
        command: str,
        timeout_seconds: float,
        native_user_memory_path: Path | None,
        native_user_memory_char_limit: int,
        runner=subprocess.run,
    ):
        self.command = command.strip()
        self.timeout_seconds = timeout_seconds
        self.native_user_memory_path = native_user_memory_path
        self.native_user_memory_char_limit = native_user_memory_char_limit
        self.runner = runner

    def ingest_quotes(self, quotes: list[Any]) -> HermesQuoteIngestResult:
        argv = shlex.split(self.command)
        if not argv:
            raise HermesQuoteIngestError("Hermes quote ingest command is empty")
        payload = self._build_payload(quotes)
        try:
            completed = self.runner(
                argv,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise HermesQuoteIngestError("Hermes quote ingest command not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise HermesQuoteIngestError("Hermes quote ingest timed out") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or "").strip() or (completed.stdout or "").strip()
            raise HermesQuoteIngestError(f"Hermes quote ingest failed: {detail[:500]}")
        try:
            response = json.loads(completed.stdout or "")
        except json.JSONDecodeError as exc:
            raise HermesQuoteIngestError("Hermes quote ingest returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise HermesQuoteIngestError("Hermes quote ingest returned non-object JSON")

        result = self._normalize_response(response)
        if result.should_update_native_memory:
            if self.native_user_memory_path is None:
                raise HermesQuoteIngestError("Hermes native USER memory path is disabled")
            if not result.memory_entry:
                raise HermesQuoteIngestError("Hermes requested quote memory update with empty entry")
            upsert_hermes_user_memory_entry(
                path=self.native_user_memory_path,
                entry=result.memory_entry,
                char_limit=self.native_user_memory_char_limit,
            )
            return HermesQuoteIngestResult(
                status="applied",
                should_update_native_memory=True,
                native_memory_path=str(self.native_user_memory_path),
                memory_entry=result.memory_entry,
                rationale=result.rationale,
                confidence=result.confidence,
                evidence_summary=result.evidence_summary,
                preference_summary=result.preference_summary,
                raw_response=result.raw_response,
            )
        return result

    def _build_payload(self, quotes: list[Any]) -> dict[str, Any]:
        return {
            "route": "reading.quote.ingest",
            "domain": "reading",
            "tool_policy": "none",
            "output_schema": "quote_profile_update_v1",
            "format": "json",
            "system_prompt": "Return exactly one JSON object for a controlled Hermes quote preference profile update decision.",
            "user_prompt": (
                "Analyze this batch of ARC reading quotes as preference evidence. "
                "Summarize repeated language, aesthetic, theme, emotion, abstraction, and narrative-density preferences. "
                "Use current_native_user_memory_entry as the existing long-term reading profile. "
                "Only update Hermes native USER memory when the quote batch shows a meaningful repeated preference or a clear self-reported note. "
                "Do not overfit to one isolated quote. If updating, output one compact declarative memory entry prefixed with "
                "'[arc-reading-profile] User reading profile:'. "
                "Output JSON keys: should_update_native_memory, memory_entry, rationale, confidence, evidence_summary, preference_summary."
            ),
            "context": {
                "current_native_user_memory_entry": read_hermes_user_memory_entry(self.native_user_memory_path),
                "quote_batch": [_quote_payload(row) for row in quotes],
            },
            "output_contract": {
                "should_update_native_memory": "boolean",
                "memory_entry": "string, empty when no update",
                "rationale": "string",
                "confidence": "number 0..1",
                "evidence_summary": "string",
                "preference_summary": {
                    "language_style": ["string"],
                    "themes": ["string"],
                    "emotional_tone": ["string"],
                    "aesthetic_signals": ["string"],
                    "open_questions": ["string"],
                },
            },
            "constraints": {
                "do_not_modify_sqlite": True,
                "do_not_send_messages": True,
                "do_not_apply_patches": True,
                "do_not_modify_memories": True,
                "business_orchestrator_writes_native_user_memory": True,
                "batch_level_summary_required": True,
                "single_isolated_quote_should_skip": True,
            },
        }

    def _normalize_response(self, response: dict[str, Any]) -> HermesQuoteIngestResult:
        should_update = _as_bool(response.get("should_update_native_memory"))
        preference_summary = response.get("preference_summary")
        if not isinstance(preference_summary, dict):
            preference_summary = {}
        try:
            confidence = float(response.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        return HermesQuoteIngestResult(
            status="skipped",
            should_update_native_memory=should_update,
            native_memory_path=str(self.native_user_memory_path or ""),
            memory_entry=str(response.get("memory_entry") or "").strip(),
            rationale=str(response.get("rationale") or "").strip(),
            confidence=confidence,
            evidence_summary=str(response.get("evidence_summary") or "").strip(),
            preference_summary=preference_summary,
            raw_response=response,
        )


class QuoteProfileIngestService:
    def __init__(self, repo: Repository, ingestor: HermesQuoteProfileIngestor):
        self.repo = repo
        self.ingestor = ingestor

    def ingest_pending(self, limit: int = 12) -> QuoteIngestSummary:
        quotes = self.repo.pending_quote_profile_ingest_batch(limit=max(1, min(int(limit), 50)))
        if not quotes:
            return QuoteIngestSummary(quote_count=0, status="empty", event_id=None)
        quote_ids = [int(row["id"]) for row in quotes]
        try:
            result = self.ingestor.ingest_quotes(quotes)
        except Exception as exc:
            event_id = self.repo.record_hermes_quote_profile_update_event(
                HermesQuoteProfileUpdateEventDraft(
                    quote_ids=quote_ids,
                    status="failed",
                    should_update_native_memory=False,
                    native_memory_path="",
                    memory_entry="",
                    rationale="",
                    confidence=0.0,
                    evidence_summary="",
                    preference_summary={},
                    error_message=str(exc),
                    raw_response={},
                )
            )
            self.repo.mark_reading_quotes_profile_ingested(quote_ids, "failed")
            logger.warning("Hermes quote ingest failed: quote_count=%s error=%s", len(quote_ids), exc)
            return QuoteIngestSummary(quote_count=len(quote_ids), status="failed", event_id=event_id)

        event_id = self.repo.record_hermes_quote_profile_update_event(
            HermesQuoteProfileUpdateEventDraft(
                quote_ids=quote_ids,
                status=result.status,
                should_update_native_memory=result.should_update_native_memory,
                native_memory_path=result.native_memory_path,
                memory_entry=result.memory_entry,
                rationale=result.rationale,
                confidence=result.confidence,
                evidence_summary=result.evidence_summary,
                preference_summary=result.preference_summary,
                error_message="",
                raw_response=result.raw_response,
            )
        )
        self.repo.mark_reading_quotes_profile_ingested(quote_ids, result.status)
        return QuoteIngestSummary(quote_count=len(quote_ids), status=result.status, event_id=event_id)


def _quote_payload(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "reading_pack_id": int(row["reading_pack_id"]),
        "recommendation_id": int(row["recommendation_id"]),
        "book": {
            "title": str(row["book_title"] or ""),
            "author": str(row["book_author"] or ""),
        },
        "quote": str(row["selected_text"] or "")[:800],
        "note": str(row["note"] or "")[:500],
        "module": str(row["module"] or ""),
        "section_title": str(row["section_title"] or ""),
        "theme": str(row["theme"] or ""),
        "slot_type": str(row["slot_type"] or ""),
        "profile_mapping": str(row["profile_mapping"] or ""),
        "system_hypothesis": str(row["system_hypothesis"] or ""),
        "created_at": str(row["created_at"] or ""),
    }


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False
