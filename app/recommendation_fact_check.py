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

RECOMMENDATION_FACT_CHECK_SCHEMA_VERSION = "recommendation_fact_check_v1"
RECOMMENDATION_FACT_CHECK_ROUTE = "reading.recommend.fact_check_v1"


class RecommendationFactCheckService:
    def __init__(
        self,
        repo: Repository,
        library_dir: Path,
        enabled: bool | None = None,
    ):
        self.repo = repo
        self.library_dir = library_dir
        self.enabled = _env_bool("ARC_ENABLE_RECOMMEND_FACT_CHECK", False) if enabled is None else enabled

    def run(
        self,
        run_id: int,
        agent: Any,
        profile_context: str,
        recommendation_history_context: str,
        themes: list[str],
        selected_recommendations: list[RecommendationDraft],
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        checker = getattr(agent, "fact_check_recommendations", None)
        if not callable(checker):
            warning = "recommendation fact check skipped: daily agent does not support reading.recommend.fact_check_v1"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        try:
            fact_check = checker(
                profile_context=profile_context,
                recommendation_history_context=recommendation_history_context,
                themes=themes,
                selected_recommendations=[_draft_to_payload(draft) for draft in selected_recommendations],
            )
        except Exception as exc:
            warning = f"recommendation fact check failed: {exc}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        if not isinstance(fact_check, dict):
            warning = "recommendation fact check failed: route returned non-object JSON"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        provider = str(getattr(agent, "name", "unknown") or "unknown")
        checks = fact_check.get("checks")
        check_count = len(checks) if isinstance(checks, list) else 0
        self.repo.record_cost(
            run_id,
            provider,
            RECOMMENDATION_FACT_CHECK_ROUTE,
            1,
            {
                "schema_version": RECOMMENDATION_FACT_CHECK_SCHEMA_VERSION,
                "check_count": check_count,
                "hint_only": True,
            },
        )
        artifact_id = self._write_artifact(
            run_id=run_id,
            provider=provider,
            themes=themes,
            selected_recommendations=selected_recommendations,
            fact_check=fact_check,
        )
        return {**fact_check, "artifact_id": artifact_id}

    def _write_artifact(
        self,
        run_id: int,
        provider: str,
        themes: list[str],
        selected_recommendations: list[RecommendationDraft],
        fact_check: dict[str, Any],
    ) -> int:
        now = datetime.now()
        artifact_dir = self.library_dir / "fact-checks" / f"{now:%Y}" / f"{now:%m}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{now:%Y-%m-%d}__run-{run_id}__fact-check.json"
        payload = {
            "schema_version": RECOMMENDATION_FACT_CHECK_SCHEMA_VERSION,
            "route": RECOMMENDATION_FACT_CHECK_ROUTE,
            "run_id": run_id,
            "hint_only": True,
            "provider": provider,
            "created_at": now.isoformat(timespec="seconds"),
            "themes": themes[:6],
            "selected_recommendations": [_draft_to_payload(draft) for draft in selected_recommendations],
            "fact_check": fact_check,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        artifact_path.write_text(raw, encoding="utf-8")
        sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        checks = fact_check.get("checks")
        return self.repo.add_or_update_artifact(
            artifact_type="recommendation_fact_check",
            title=f"Recommendation fact check run {run_id}",
            path=str(artifact_path),
            sha256=sha256,
            content_type="application/json",
            metadata={
                "schema_version": RECOMMENDATION_FACT_CHECK_SCHEMA_VERSION,
                "route": RECOMMENDATION_FACT_CHECK_ROUTE,
                "run_id": run_id,
                "hint_only": True,
                "provider": provider,
                "check_count": len(checks) if isinstance(checks, list) else 0,
            },
        )


def _draft_to_payload(draft: RecommendationDraft) -> dict[str, Any]:
    return {
        "title": draft.title,
        "author": draft.author,
        "source_url": draft.source_url,
        "slot_type": draft.slot_type,
        "theme": draft.theme,
        "reading_suggestion": draft.reading_suggestion,
    }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
