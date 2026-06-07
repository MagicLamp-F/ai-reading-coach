from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.memory import read_hermes_user_memory_entry, upsert_hermes_user_memory_entry


class HermesProfileIngestError(RuntimeError):
    pass


@dataclass(frozen=True)
class HermesProfileIngestResult:
    status: str
    should_update_native_memory: bool
    native_memory_path: str
    memory_entry: str
    rationale: str
    confidence: float
    evidence_summary: str
    raw_response: dict[str, Any]


class FeedbackProfileIngestor(Protocol):
    def ingest_feedback(self, event: Any) -> HermesProfileIngestResult:
        ...


class HermesFeedbackProfileIngestor:
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

    def ingest_feedback(self, event: Any) -> HermesProfileIngestResult:
        argv = shlex.split(self.command)
        if not argv:
            raise HermesProfileIngestError("Hermes feedback ingest command is empty")

        payload = self._build_payload(event)
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
            raise HermesProfileIngestError("Hermes feedback ingest command not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise HermesProfileIngestError("Hermes feedback ingest timed out") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or "").strip() or (completed.stdout or "").strip()
            raise HermesProfileIngestError(f"Hermes feedback ingest failed: {detail[:500]}")

        try:
            response = json.loads(completed.stdout or "")
        except json.JSONDecodeError as exc:
            raise HermesProfileIngestError("Hermes feedback ingest returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise HermesProfileIngestError("Hermes feedback ingest returned non-object JSON")

        result = self._normalize_response(response)
        if result.should_update_native_memory:
            if self.native_user_memory_path is None:
                raise HermesProfileIngestError("Hermes native USER memory path is disabled")
            if not result.memory_entry:
                raise HermesProfileIngestError("Hermes requested native memory update with empty entry")
            upsert_hermes_user_memory_entry(
                path=self.native_user_memory_path,
                entry=result.memory_entry,
                char_limit=self.native_user_memory_char_limit,
            )
            return HermesProfileIngestResult(
                status="applied",
                should_update_native_memory=True,
                native_memory_path=str(self.native_user_memory_path),
                memory_entry=result.memory_entry,
                rationale=result.rationale,
                confidence=result.confidence,
                evidence_summary=result.evidence_summary,
                raw_response=result.raw_response,
            )
        return result

    def _build_payload(self, event: Any) -> dict[str, Any]:
        context = {
            "current_native_user_memory_entry": read_hermes_user_memory_entry(self.native_user_memory_path),
            "feedback_event": {
                "id": int(event["id"]),
                "recommendation_id": int(event["recommendation_id"]),
                "feedback_type": str(event["feedback_type"] or ""),
                "reason_code": str(event["reason_code"] or ""),
                "free_text": str(event["free_text"] or ""),
                "created_at": str(event["created_at"] or ""),
            },
            "recommendation": {
                "title": str(event["title"] or ""),
                "author": str(event["author"] or ""),
                "theme": str(event["theme"] or ""),
                "slot_type": str(event["slot_type"] or ""),
                "profile_mapping": str(event["profile_mapping"] or ""),
            },
        }
        return {
            "route": "reading.feedback.ingest",
            "domain": "reading",
            "tool_policy": "none",
            "output_schema": "profile_update_v1",
            "format": "json",
            "system_prompt": "Return exactly one JSON object for a controlled Hermes native USER memory update decision.",
            "user_prompt": (
                "Decide whether this ARC reading feedback should update Hermes native USER memory. "
                "Use current_native_user_memory_entry as the existing long-term reading profile; preserve stable facts unless the new feedback clearly corrects them. "
                "Only update for explicit self-report, repeated/high-signal preference, or a clear correction. "
                "Do not turn one weak click into a long-term identity claim. "
                "If updating, output one compact declarative memory entry prefixed with "
                "'[arc-reading-profile] User reading profile:'. "
                "Output JSON keys: should_update_native_memory, memory_entry, rationale, confidence, evidence_summary."
            ),
            "context": context,
            "output_contract": {
                "should_update_native_memory": "boolean",
                "memory_entry": "string, empty when no update",
                "rationale": "string",
                "confidence": "number 0..1",
                "evidence_summary": "string",
            },
            "constraints": {
                "do_not_modify_sqlite": True,
                "do_not_send_messages": True,
                "do_not_apply_patches": True,
                "do_not_modify_memories": True,
                "business_orchestrator_writes_native_user_memory": True,
                "single_weak_signal_should_skip": True,
            },
        }

    def _normalize_response(self, response: dict[str, Any]) -> HermesProfileIngestResult:
        should_update = _as_bool(response.get("should_update_native_memory"))
        memory_entry = str(response.get("memory_entry") or "").strip()
        rationale = str(response.get("rationale") or "").strip()
        evidence_summary = str(response.get("evidence_summary") or "").strip()
        try:
            confidence = float(response.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        return HermesProfileIngestResult(
            status="skipped",
            should_update_native_memory=should_update,
            native_memory_path=str(self.native_user_memory_path or ""),
            memory_entry=memory_entry,
            rationale=rationale,
            confidence=confidence,
            evidence_summary=evidence_summary,
            raw_response=response,
        )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False
