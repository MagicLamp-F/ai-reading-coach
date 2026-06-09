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
SHADOW_COMPARISON_SCHEMA_VERSION = "recommendation_shadow_comparison_v1"


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
        max_subagents = _env_int("ARC_AGENTIC_SHADOW_MAX_SUBAGENTS", 2, 0, 8)
        max_wall_time_seconds = _env_int("ARC_AGENTIC_SHADOW_TIMEOUT_SECONDS", 90, 1, 600)
        max_model_calls = _env_int("ARC_AGENTIC_SHADOW_MAX_MODEL_CALLS", 1, 0, 20)
        max_search_calls = _env_int("ARC_AGENTIC_SHADOW_MAX_SEARCH_CALLS", 0, 0, 50)
        allow_web_search = _env_bool("ARC_AGENTIC_SHADOW_ALLOW_WEB_SEARCH", False)
        allow_memory = _env_bool("ARC_AGENTIC_SHADOW_ALLOW_MEMORY", False)
        allow_file = _env_bool("ARC_AGENTIC_SHADOW_ALLOW_FILE", False)
        allow_terminal = _env_bool("ARC_AGENTIC_SHADOW_ALLOW_TERMINAL", False)
        allow_session_search = _env_bool("ARC_AGENTIC_SHADOW_ALLOW_SESSION_SEARCH", False)
        tool_permissions = _tool_permissions(
            allow_web_search=allow_web_search,
            allow_memory=allow_memory,
            allow_file=allow_file,
            allow_terminal=allow_terminal,
            allow_session_search=allow_session_search,
        )
        self.shadow_config = {
            "max_subagents": max_subagents,
            "timeout_seconds": max_wall_time_seconds,
            "max_wall_time_seconds": max_wall_time_seconds,
            "max_model_calls": max_model_calls,
            "max_search_calls": max_search_calls,
            "allow_web_search": allow_web_search,
            "allow_memory": allow_memory,
            "allow_file": allow_file,
            "allow_terminal": allow_terminal,
            "allow_session_search": allow_session_search,
            "side_effects_allowed": False,
            "tool_permissions": tool_permissions,
            "delegation_policy": _delegation_policy(
                max_subagents=max_subagents,
                max_wall_time_seconds=max_wall_time_seconds,
                max_model_calls=max_model_calls,
                max_search_calls=max_search_calls,
                tool_permissions=tool_permissions,
            ),
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
            "delegation_mode": self.shadow_config["delegation_policy"]["mode"],
            "bounded_delegation_allowed": self.shadow_config["delegation_policy"]["bounded_delegation_allowed"],
            "max_wall_time_seconds": self.shadow_config["max_wall_time_seconds"],
            "max_model_calls": self.shadow_config["max_model_calls"],
            "max_search_calls": self.shadow_config["max_search_calls"],
            "tool_permission_default": self.shadow_config["tool_permissions"]["default"],
            "side_effects_allowed": self.shadow_config["side_effects_allowed"],
        }
        self.repo.record_cost(run_id, provider, AGENTIC_SHADOW_ROUTE, 1, metadata)
        shadow_artifact_id = self._write_artifact(
            run_id=run_id,
            provider=provider,
            latency_ms=latency_ms,
            themes=themes,
            recommendation_plan=recommendation_plan,
            generated_candidates=generated_candidates,
            selected_recommendations=selected_recommendations,
            shadow=shadow,
        )
        self._write_comparison_artifact(
            run_id=run_id,
            provider=provider,
            latency_ms=latency_ms,
            generated_candidates=generated_candidates,
            selected_recommendations=selected_recommendations,
            shadow=shadow,
        )
        return shadow_artifact_id

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
                "delegation_mode": self.shadow_config["delegation_policy"]["mode"],
                "bounded_delegation_allowed": self.shadow_config["delegation_policy"]["bounded_delegation_allowed"],
                "max_wall_time_seconds": self.shadow_config["max_wall_time_seconds"],
                "max_model_calls": self.shadow_config["max_model_calls"],
                "max_search_calls": self.shadow_config["max_search_calls"],
                "tool_permission_default": self.shadow_config["tool_permissions"]["default"],
                "side_effects_allowed": self.shadow_config["side_effects_allowed"],
            },
        )

    def _write_comparison_artifact(
        self,
        run_id: int,
        provider: str,
        latency_ms: int,
        generated_candidates: list[RecommendationDraft],
        selected_recommendations: list[RecommendationDraft],
        shadow: dict[str, Any],
    ) -> int:
        now = datetime.now()
        artifact_dir = self.library_dir / "shadow-comparisons" / f"{now:%Y}" / f"{now:%m}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{now:%Y-%m-%d}__run-{run_id}__shadow-comparison.json"
        comparison = _build_shadow_comparison(
            run_id=run_id,
            provider=provider,
            latency_ms=latency_ms,
            generated_candidates=generated_candidates,
            selected_recommendations=selected_recommendations,
            shadow=shadow,
        )
        payload = {
            "schema_version": SHADOW_COMPARISON_SCHEMA_VERSION,
            "run_id": run_id,
            "shadow_route": AGENTIC_SHADOW_ROUTE,
            "created_at": now.isoformat(timespec="seconds"),
            "comparison": comparison,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        artifact_path.write_text(raw, encoding="utf-8")
        sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.repo.add_or_update_artifact(
            artifact_type="recommendation_shadow_comparison",
            title=f"Recommendation shadow comparison run {run_id}",
            path=str(artifact_path),
            sha256=sha256,
            content_type="application/json",
            metadata={
                "schema_version": SHADOW_COMPARISON_SCHEMA_VERSION,
                "run_id": run_id,
                "shadow_route": AGENTIC_SHADOW_ROUTE,
                "provider": provider,
                "baseline_count": len(selected_recommendations),
                "shadow_count": len(shadow.get("shadow_recommendations", []))
                if isinstance(shadow.get("shadow_recommendations"), list)
                else 0,
                "latency_ms": latency_ms,
                "feedback_alignment_status": "pending_future_feedback",
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


def _build_shadow_comparison(
    run_id: int,
    provider: str,
    latency_ms: int,
    generated_candidates: list[RecommendationDraft],
    selected_recommendations: list[RecommendationDraft],
    shadow: dict[str, Any],
) -> dict[str, Any]:
    shadow_recommendations = shadow.get("shadow_recommendations")
    if not isinstance(shadow_recommendations, list):
        shadow_recommendations = []
    shadow_items = [item for item in shadow_recommendations if isinstance(item, dict)]
    baseline_keys = {_book_key(draft.title, draft.author) for draft in selected_recommendations}
    shadow_keys = {
        _book_key(str(item.get("title", "")), str(item.get("author", "")))
        for item in shadow_items
        if str(item.get("title", "")).strip()
    }
    overlap_keys = baseline_keys.intersection(shadow_keys)
    replacement_count = sum(1 for item in shadow_items if str(item.get("replace_baseline_title", "")).strip())
    shadow_with_source = sum(1 for item in shadow_items if str(item.get("source_url", "")).strip())
    baseline_assessment = shadow.get("baseline_assessment")
    if not isinstance(baseline_assessment, dict):
        baseline_assessment = {}

    return {
        "run_id": run_id,
        "provider": provider,
        "baseline": {
            "count": len(selected_recommendations),
            "books": [_draft_to_payload(draft) for draft in selected_recommendations],
            "metrics": {
                "profile_fit": _float_value(baseline_assessment.get("profile_fit"), None),
                "novelty": _float_value(baseline_assessment.get("novelty"), None),
                "start_path_quality": _float_value(baseline_assessment.get("start_path_quality"), None),
                "source_validity": _float_value(baseline_assessment.get("source_validity"), None),
            },
            "risks": _string_list(baseline_assessment.get("risks"), 20, 500),
        },
        "shadow": {
            "count": len(shadow_items),
            "books": shadow_items[:12],
            "metrics": {
                "profile_fit": None,
                "novelty_proxy": _ratio(len(shadow_keys.difference(baseline_keys)), len(shadow_keys)),
                "start_path_quality": None,
                "source_validity_proxy": _ratio(shadow_with_source, len(shadow_items)),
            },
            "subagents_used": _int_value(shadow.get("subagents_used"), 0),
            "roles": _string_list(shadow.get("roles"), 8, 120),
            "trace_mode": str(shadow.get("trace_mode") or ""),
            "delegation_mode": "simulated_trace",
            "warnings": _string_list(shadow.get("warnings"), 20, 500),
            "confidence": _float_value(shadow.get("confidence"), 0.0),
        },
        "comparison": {
            "candidate_count": len(generated_candidates),
            "overlap_count": len(overlap_keys),
            "replacement_suggestion_count": replacement_count,
            "shadow_source_url_coverage": _ratio(shadow_with_source, len(shadow_items)),
            "latency_ms": latency_ms,
            "cost_units": 1,
            "agent_recommended_action": _agent_recommended_action(shadow),
        },
        "feedback_alignment": {
            "status": "pending_future_feedback",
            "baseline_book_keys": sorted(baseline_keys),
            "shadow_book_keys": sorted(shadow_keys),
            "note": "Alignment requires future feedback_events for the delivered baseline recommendations.",
        },
    }


def _book_key(title: str, author: str) -> str:
    return f"{title.strip().lower()}::{author.strip().lower()}"


def _agent_recommended_action(shadow: dict[str, Any]) -> str:
    comparison = shadow.get("comparison")
    if not isinstance(comparison, dict):
        return ""
    return str(comparison.get("recommended_action") or "")[:120]


def _delegation_policy(
    max_subagents: int,
    max_wall_time_seconds: int,
    max_model_calls: int,
    max_search_calls: int,
    tool_permissions: dict[str, Any],
) -> dict[str, Any]:
    allowed_roles = [
        "profile_history_reviewer",
        "source_quality_reviewer",
        "reading_pack_reviewer",
        "hard_exclusion_reviewer",
    ]
    return {
        "mode": "simulated_trace",
        "bounded_delegation_allowed": False,
        "max_subagents": max_subagents,
        "max_wall_time_seconds": max_wall_time_seconds,
        "max_model_calls": max_model_calls,
        "max_search_calls": max_search_calls,
        "allowed_roles": allowed_roles[:max_subagents],
        "read_only": True,
        "side_effects_allowed": False,
        "tool_permissions": tool_permissions,
        "requires_agentic_wrapper": "hermes-agentic-json",
    }


def _tool_permissions(
    allow_web_search: bool,
    allow_memory: bool,
    allow_file: bool,
    allow_terminal: bool,
    allow_session_search: bool,
) -> dict[str, Any]:
    return {
        "default": "read_only",
        "allow_web_search": allow_web_search,
        "allow_memory_read": allow_memory,
        "allow_file_read": allow_file,
        "allow_terminal": allow_terminal,
        "allow_session_search": allow_session_search,
        "allow_file_write": False,
        "allow_database_write": False,
        "allow_memory_write": False,
        "allow_message_send": False,
        "allow_delivery_state_change": False,
        "forbidden_side_effects": [
            "file_write",
            "database_write",
            "memory_write",
            "message_send",
            "delivery_state_change",
        ],
    }


def _string_list(raw: Any, limit: int, max_chars: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip()[:max_chars] for item in raw if str(item).strip()][:limit]


def _float_value(raw: Any, default: float | None) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 3)


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
