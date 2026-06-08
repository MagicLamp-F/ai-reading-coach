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

RECOMMENDATION_REVIEW_SCHEMA_VERSION = "recommendation_review_v1"
RECOMMENDATION_REVIEW_ROUTE = "reading.recommend.review_v1"


class RecommendationReviewShadowService:
    def __init__(
        self,
        repo: Repository,
        library_dir: Path,
        enabled: bool | None = None,
    ):
        self.repo = repo
        self.library_dir = library_dir
        self.enabled = _env_bool("ARC_ENABLE_RECOMMEND_REVIEW_SHADOW", False) if enabled is None else enabled

    def run(
        self,
        run_id: int,
        agent: Any,
        profile_context: str,
        recommendation_history_context: str,
        themes: list[str],
        generated_candidates: list[RecommendationDraft],
        selected_recommendations: list[RecommendationDraft],
    ) -> int | None:
        if not self.enabled:
            return None
        reviewer = getattr(agent, "review_recommendations", None)
        if not callable(reviewer):
            warning = "recommendation review shadow skipped: daily agent does not support reading.recommend.review_v1"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        try:
            review = reviewer(
                profile_context=profile_context,
                recommendation_history_context=recommendation_history_context,
                themes=themes,
                generated_candidates=[_draft_to_payload(draft) for draft in generated_candidates],
                selected_recommendations=[_draft_to_payload(draft) for draft in selected_recommendations],
            )
        except Exception as exc:
            warning = f"recommendation review shadow failed: {exc}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        if not isinstance(review, dict):
            warning = "recommendation review shadow failed: route returned non-object JSON"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        provider = str(getattr(agent, "name", "unknown") or "unknown")
        self.repo.record_cost(
            run_id,
            provider,
            RECOMMENDATION_REVIEW_ROUTE,
            1,
            {
                "schema_version": RECOMMENDATION_REVIEW_SCHEMA_VERSION,
                "generated_candidates": len(generated_candidates),
                "selected_recommendations": len(selected_recommendations),
                "shadow": True,
            },
        )
        return self._write_artifact(
            run_id=run_id,
            provider=provider,
            themes=themes,
            generated_candidates=generated_candidates,
            selected_recommendations=selected_recommendations,
            review=review,
        )

    def _write_artifact(
        self,
        run_id: int,
        provider: str,
        themes: list[str],
        generated_candidates: list[RecommendationDraft],
        selected_recommendations: list[RecommendationDraft],
        review: dict[str, Any],
    ) -> int:
        now = datetime.now()
        artifact_dir = self.library_dir / "recommendation-reviews" / f"{now:%Y}" / f"{now:%m}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{now:%Y-%m-%d}__run-{run_id}__review.json"
        payload = {
            "schema_version": RECOMMENDATION_REVIEW_SCHEMA_VERSION,
            "route": RECOMMENDATION_REVIEW_ROUTE,
            "run_id": run_id,
            "shadow": True,
            "provider": provider,
            "created_at": now.isoformat(timespec="seconds"),
            "themes": themes[:6],
            "generated_candidates": [_draft_to_payload(draft) for draft in generated_candidates],
            "selected_recommendations": [_draft_to_payload(draft) for draft in selected_recommendations],
            "review": review,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        artifact_path.write_text(raw, encoding="utf-8")
        sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.repo.add_or_update_artifact(
            artifact_type="recommendation_review",
            title=f"Recommendation review shadow run {run_id}",
            path=str(artifact_path),
            sha256=sha256,
            content_type="application/json",
            metadata={
                "schema_version": RECOMMENDATION_REVIEW_SCHEMA_VERSION,
                "route": RECOMMENDATION_REVIEW_ROUTE,
                "run_id": run_id,
                "shadow": True,
                "provider": provider,
                "verdict": str(review.get("verdict") or review.get("overall_verdict") or ""),
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
