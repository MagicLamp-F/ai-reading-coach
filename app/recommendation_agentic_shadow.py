from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.repository import RecommendationDraft, Repository

logger = logging.getLogger(__name__)

AGENTIC_SHADOW_SCHEMA_VERSION = "agentic_shadow_v1"
AGENTIC_SHADOW_ROUTE = "reading.recommend.agentic_shadow_v1"


class RecommendationAgenticShadowService:
    def __init__(
        self,
        repo: Repository,
        library_dir: Path,
        enabled: bool | None = None,
    ):
        self.repo = repo
        self.library_dir = library_dir
        self.enabled = _env_bool("ARC_ENABLE_AGENTIC_SHADOW", False) if enabled is None else enabled
        self.shadow_config = {
            "max_subagents": _env_int("ARC_AGENTIC_SHADOW_MAX_SUBAGENTS", 2, 0, 8),
            "timeout_seconds": _env_int("ARC_AGENTIC_SHADOW_TIMEOUT_SECONDS", 90, 1, 600),
            "allow_web_search": _env_bool("ARC_AGENTIC_SHADOW_ALLOW_WEB_SEARCH", False),
            "allow_memory": _env_bool("ARC_AGENTIC_SHADOW_ALLOW_MEMORY", False),
            "allow_file": _env_bool("ARC_AGENTIC_SHADOW_ALLOW_FILE", False),
            "allow_terminal": _env_bool("ARC_AGENTIC_SHADOW_ALLOW_TERMINAL", False),
            "allow_session_search": _env_bool("ARC_AGENTIC_SHADOW_ALLOW_SESSION_SEARCH", False),
            "side_effects_allowed": False,
        }

    def run(
        self,
        run_id: int,
        agent: Any,
        profile_context: str,
        recommendation_history_context: str,
        themes: list[str],
        recommendation_plan: dict[str, Any] | None,
        generated_candidates: list[RecommendationDraft],
        selected_recommendations: list[RecommendationDraft],
    ) -> int | None:
        if not self.enabled:
            return None
        shadow_runner = getattr(agent, "agentic_shadow_recommendations", None)
        if not callable(shadow_runner):
            warning = "agentic shadow skipped: daily agent does not support reading.recommend.agentic_shadow_v1"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        started = time.perf_counter()
        try:
            shadow = shadow_runner(
                profile_context=profile_context,
                recommendation_history_context=recommendation_history_context,
                themes=themes,
                recommendation_plan=recommendation_plan,
                generated_candidates=[_draft_to_payload(draft) for draft in generated_candidates],
                selected_recommendations=[_draft_to_payload(draft) for draft in selected_recommendations],
                shadow_config=self.shadow_config,
            )
        except Exception as exc:
            warning = f"agentic shadow failed: {exc}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None
        latency_ms = int((time.perf_counter() - started) * 1000)

        if not isinstance(shadow, dict):
            warning = "agentic shadow failed: route returned non-object JSON"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        provider = str(getattr(agent, "name", "unknown") or "unknown")
        metadata = {
            "schema_version": AGENTIC_SHADOW_SCHEMA_VERSION,
            "route": AGENTIC_SHADOW_ROUTE,
            "shadow": True,
            "hint_only": True,
            "subagents_used": _int_value(shadow.get("subagents_used"), 0),
            "roles": [str(role)[:120] for role in shadow.get("roles", []) if str(role).strip()][:8]
            if isinstance(shadow.get("roles"), list)
            else [],
            "latency_ms": latency_ms,
            "warning_count": len(shadow.get("warnings", [])) if isinstance(shadow.get("warnings"), list) else 0,
            "trace_mode": str(shadow.get("trace_mode") or ""),
        }
        self.repo.record_cost(run_id, provider, AGENTIC_SHADOW_ROUTE, 1, metadata)
        return self._write_artifact(
            run_id=run_id,
            provider=provider,
            latency_ms=latency_ms,
            themes=themes,
            recommendation_plan=recommendation_plan,
            generated_candidates=generated_candidates,
            selected_recommendations=selected_recommendations,
            shadow=shadow,
        )

    def _write_artifact(
        self,
        run_id: int,
        provider: str,
        latency_ms: int,
        themes: list[str],
        recommendation_plan: dict[str, Any] | None,
        generated_candidates: list[RecommendationDraft],
        selected_recommendations: list[RecommendationDraft],
        shadow: dict[str, Any],
    ) -> int:
        now = datetime.now()
        artifact_dir = self.library_dir / "agentic-shadows" / f"{now:%Y}" / f"{now:%m}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{now:%Y-%m-%d}__run-{run_id}__agentic-shadow.json"
        payload = {
            "schema_version": AGENTIC_SHADOW_SCHEMA_VERSION,
            "route": AGENTIC_SHADOW_ROUTE,
            "run_id": run_id,
            "shadow": True,
            "hint_only": True,
            "provider": provider,
            "created_at": now.isoformat(timespec="seconds"),
            "latency_ms": latency_ms,
            "shadow_config": self.shadow_config,
            "themes": themes[:6],
            "recommendation_plan": recommendation_plan or {},
            "generated_candidates": [_draft_to_payload(draft) for draft in generated_candidates],
            "selected_recommendations": [_draft_to_payload(draft) for draft in selected_recommendations],
            "agentic_shadow": shadow,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        artifact_path.write_text(raw, encoding="utf-8")
        sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.repo.add_or_update_artifact(
            artifact_type="recommendation_agentic_shadow",
            title=f"Recommendation agentic shadow run {run_id}",
            path=str(artifact_path),
            sha256=sha256,
            content_type="application/json",
            metadata={
                "schema_version": AGENTIC_SHADOW_SCHEMA_VERSION,
                "route": AGENTIC_SHADOW_ROUTE,
                "run_id": run_id,
                "shadow": True,
                "hint_only": True,
                "provider": provider,
                "subagents_used": _int_value(shadow.get("subagents_used"), 0),
                "trace_mode": str(shadow.get("trace_mode") or ""),
                "latency_ms": latency_ms,
            },
        )


def _draft_to_payload(draft: RecommendationDraft) -> dict[str, Any]:
    return {
        "title": draft.title,
        "author": draft.author,
        "source_url": draft.source_url,
        "slot_type": draft.slot_type,
        "theme": draft.theme,
        "system_hypothesis": draft.system_hypothesis,
        "profile_dimensions": draft.profile_dimensions,
        "recommendation_reason": draft.recommendation_reason,
        "profile_mapping": draft.profile_mapping,
        "expected_benefit": draft.expected_benefit,
        "risk": draft.risk,
        "reading_suggestion": draft.reading_suggestion,
        "metadata": draft.metadata,
    }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def _int_value(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
