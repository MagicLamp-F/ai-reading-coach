from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.repository import RecommendationDraft, Repository

logger = logging.getLogger(__name__)

RECOMMENDATION_GATING_SCHEMA_VERSION = "recommendation_gating_decision_v1"


class RecommendationGatingService:
    def __init__(
        self,
        repo: Repository,
        library_dir: Path,
        enabled: bool | None = None,
        enforce_block: bool | None = None,
    ):
        self.repo = repo
        self.library_dir = library_dir
        self.enabled = _env_bool("ARC_ENABLE_REVIEW_GATING", False) if enabled is None else enabled
        self.enforce_block = _env_bool("ARC_REVIEW_GATING_ENFORCE_BLOCK", False) if enforce_block is None else enforce_block

    def run(
        self,
        run_id: int,
        selected_recommendations: list[RecommendationDraft],
        target_count: int,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        review_artifact = self._latest_artifact(run_id, "recommendation_review")
        shadow_artifact = self._latest_artifact(run_id, "recommendation_agentic_shadow")
        review_payload = _load_json_file(Path(str(review_artifact["path"]))) if review_artifact is not None else None
        shadow_payload = _load_json_file(Path(str(shadow_artifact["path"]))) if shadow_artifact is not None else None
        decision = _build_gating_decision(
            run_id=run_id,
            selected_recommendations=selected_recommendations,
            target_count=target_count,
            review_payload=review_payload if isinstance(review_payload, dict) else None,
            shadow_payload=shadow_payload if isinstance(shadow_payload, dict) else None,
            enforce_block=self.enforce_block,
        )
        artifact_id = self._write_artifact(run_id, decision)
        decision["artifact_id"] = artifact_id
        if decision["enforced_action"] == "block_delivery":
            warning = "review gating requested delivery block"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
        return decision

    def _latest_artifact(self, run_id: int, artifact_type: str) -> Any | None:
        return self.repo.conn.execute(
            """
            SELECT *
            FROM artifacts
            WHERE artifact_type = ?
                AND json_extract(metadata_json, '$.run_id') = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (artifact_type, run_id),
        ).fetchone()

    def _write_artifact(self, run_id: int, decision: dict[str, Any]) -> int:
        now = datetime.now()
        artifact_dir = self.library_dir / "gating-decisions" / f"{now:%Y}" / f"{now:%m}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{now:%Y-%m-%d}__run-{run_id}__gating.json"
        payload = {
            "schema_version": RECOMMENDATION_GATING_SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": now.isoformat(timespec="seconds"),
            "decision": decision,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        artifact_path.write_text(raw, encoding="utf-8")
        sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.repo.add_or_update_artifact(
            artifact_type="recommendation_gating_decision",
            title=f"Recommendation gating decision run {run_id}",
            path=str(artifact_path),
            sha256=sha256,
            content_type="application/json",
            metadata={
                "schema_version": RECOMMENDATION_GATING_SCHEMA_VERSION,
                "run_id": run_id,
                "suggested_action": decision["suggested_action"],
                "enforced_action": decision["enforced_action"],
                "enforce_block": self.enforce_block,
            },
        )


def _build_gating_decision(
    run_id: int,
    selected_recommendations: list[RecommendationDraft],
    target_count: int,
    review_payload: dict[str, Any] | None,
    shadow_payload: dict[str, Any] | None,
    enforce_block: bool,
) -> dict[str, Any]:
    review = review_payload.get("review") if isinstance(review_payload, dict) else None
    if not isinstance(review, dict):
        review = {}
    agentic_shadow = shadow_payload.get("agentic_shadow") if isinstance(shadow_payload, dict) else None
    if not isinstance(agentic_shadow, dict):
        agentic_shadow = {}

    local_confirmations = _local_gating_confirmations(selected_recommendations, target_count)
    review_verdict = str(review.get("verdict") or "").strip().lower()
    shadow_action = _shadow_recommended_action(agentic_shadow)
    suggestions = []
    if review_verdict == "reject":
        suggestions.append("suggest_block_delivery")
    elif review_verdict == "warn":
        suggestions.append("warn_delivery")
    if shadow_action in {"needs_more_evidence", "suggest_block_delivery"}:
        suggestions.append("warn_delivery")
    if any(reason["severity"] == "block" for reason in local_confirmations):
        suggestions.append("suggest_block_delivery")
    suggested_action = "allow_delivery"
    if "suggest_block_delivery" in suggestions:
        suggested_action = "suggest_block_delivery"
    elif "warn_delivery" in suggestions:
        suggested_action = "warn_delivery"

    locally_confirmed_block = any(reason["severity"] == "block" for reason in local_confirmations)
    enforced_action = "block_delivery" if enforce_block and suggested_action == "suggest_block_delivery" and locally_confirmed_block else "observe_only"
    return {
        "schema_version": RECOMMENDATION_GATING_SCHEMA_VERSION,
        "run_id": run_id,
        "mode": "enforce_block" if enforce_block else "observe_only",
        "suggested_action": suggested_action,
        "enforced_action": enforced_action,
        "review": {
            "artifact_present": review_payload is not None,
            "verdict": review_verdict,
            "revision_instruction_count": len(review.get("revision_instructions", []))
            if isinstance(review.get("revision_instructions"), list)
            else 0,
            "warning_count": len(review.get("global_warnings", [])) if isinstance(review.get("global_warnings"), list) else 0,
        },
        "agentic_shadow": {
            "artifact_present": shadow_payload is not None,
            "recommended_action": shadow_action,
            "warning_count": len(agentic_shadow.get("warnings", [])) if isinstance(agentic_shadow.get("warnings"), list) else 0,
            "subagents_used": _int_value(agentic_shadow.get("subagents_used"), 0),
        },
        "local_confirmations": local_confirmations,
        "selected_recommendations": [_draft_to_payload(draft) for draft in selected_recommendations],
        "notes": [
            "Gating is observe-only unless ARC_REVIEW_GATING_ENFORCE_BLOCK=true.",
            "LLM review/shadow suggestions cannot block delivery without ARC local block confirmation.",
        ],
    }


def _local_gating_confirmations(selected_recommendations: list[RecommendationDraft], target_count: int) -> list[dict[str, str]]:
    confirmations = []
    if not selected_recommendations:
        confirmations.append(
            {
                "code": "no_selected_recommendations",
                "severity": "block",
                "detail": "No selected recommendations are available for delivery.",
            }
        )
    elif len(selected_recommendations) < max(1, target_count):
        confirmations.append(
            {
                "code": "selected_count_below_target",
                "severity": "warn",
                "detail": f"Selected {len(selected_recommendations)} recommendation(s), target is {target_count}.",
            }
        )
    missing_reading_path = [
        draft.title for draft in selected_recommendations if not draft.reading_suggestion.strip() and not draft.source_url.strip()
    ]
    if missing_reading_path:
        confirmations.append(
            {
                "code": "missing_reading_path",
                "severity": "warn",
                "detail": "; ".join(missing_reading_path[:5]),
            }
        )
    return confirmations


def _shadow_recommended_action(agentic_shadow: dict[str, Any]) -> str:
    comparison = agentic_shadow.get("comparison")
    if not isinstance(comparison, dict):
        return ""
    return str(comparison.get("recommended_action") or "").strip().lower()


def _draft_to_payload(draft: RecommendationDraft) -> dict[str, Any]:
    return {
        "title": draft.title,
        "author": draft.author,
        "source_url": draft.source_url,
        "slot_type": draft.slot_type,
        "theme": draft.theme,
        "reading_suggestion": draft.reading_suggestion,
    }


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_value(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
