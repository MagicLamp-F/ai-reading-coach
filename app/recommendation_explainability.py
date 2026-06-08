from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.repository import RecommendationDraft, Repository

RECOMMENDATION_EXPLAINABILITY_SCHEMA_VERSION = "recommendation_candidate_explainability_v1"


class RecommendationCandidateExplainabilityService:
    def __init__(self, repo: Repository, library_dir: Path):
        self.repo = repo
        self.library_dir = library_dir

    def write_artifact(
        self,
        run_id: int,
        raw_candidates: list[RecommendationDraft],
        selected_recommendations: list[RecommendationDraft],
        hard_exclusion_keys: set[tuple[str, str]],
    ) -> int:
        candidate_rows = self.repo.list_recommendation_candidates(run_id)
        source_decisions = {
            _book_key(str(row["title"] or ""), str(row["author"] or "")): row
            for row in candidate_rows
        }
        selected_keys = {
            _book_key(draft.title, draft.author)
            for draft in selected_recommendations
        }
        items = [
            _candidate_decision(
                draft=draft,
                selected_keys=selected_keys,
                hard_exclusion_keys=hard_exclusion_keys,
                source_decision=source_decisions.get(_book_key(draft.title, draft.author)),
            )
            for draft in raw_candidates
        ]
        now = datetime.now()
        artifact_dir = self.library_dir / "recommendation-decisions" / f"{now:%Y}" / f"{now:%m}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{now:%Y-%m-%d}__run-{run_id}__candidate-decisions.json"
        payload = {
            "schema_version": RECOMMENDATION_EXPLAINABILITY_SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": now.isoformat(timespec="seconds"),
            "candidate_count": len(raw_candidates),
            "selected_count": len(selected_recommendations),
            "decisions": items,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        artifact_path.write_text(raw, encoding="utf-8")
        sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.repo.add_or_update_artifact(
            artifact_type="recommendation_candidate_explainability",
            title=f"Recommendation candidate decisions run {run_id}",
            path=str(artifact_path),
            sha256=sha256,
            content_type="application/json",
            metadata={
                "schema_version": RECOMMENDATION_EXPLAINABILITY_SCHEMA_VERSION,
                "run_id": run_id,
                "candidate_count": len(raw_candidates),
                "selected_count": len(selected_recommendations),
            },
        )


def _candidate_decision(
    draft: RecommendationDraft,
    selected_keys: set[tuple[str, str]],
    hard_exclusion_keys: set[tuple[str, str]],
    source_decision: Any,
) -> dict[str, Any]:
    key = _book_key(draft.title, draft.author)
    excluded_by: list[str] = []
    status = "candidate"
    source_scoring: dict[str, Any] = {}
    source_reject_reason = ""

    if key in hard_exclusion_keys:
        status = "rejected"
        excluded_by.append("hard_exclusion")
    elif key in selected_keys:
        status = "selected"

    if source_decision is not None:
        row_status = str(source_decision["status"] or "")
        source_reject_reason = str(source_decision["reject_reason"] or "")
        source_scoring = {
            "user_fit_score": float(source_decision["user_fit_score"] or 0),
            "source_coverage_score": float(source_decision["source_coverage_score"] or 0),
            "final_score": float(source_decision["final_score"] or 0),
            "source_status": str(source_decision["source_status"] or ""),
            "reject_reason": source_reject_reason,
        }
        if row_status == "selected":
            status = "selected"
        elif row_status == "rejected" and status != "rejected":
            status = "rejected"
        if source_reject_reason:
            excluded_by.append(source_reject_reason)

    if status == "candidate" and key not in selected_keys:
        status = "rejected"
        excluded_by.append("not_selected")

    return {
        "title": draft.title,
        "author": draft.author,
        "source_url": draft.source_url,
        "slot_type": draft.slot_type,
        "theme": draft.theme,
        "status": status,
        "excluded_by": list(dict.fromkeys(excluded_by)),
        "source_scoring": source_scoring,
        "candidate_reason": str(draft.metadata.get("candidate_reason", "")),
        "metadata": draft.metadata,
    }


def _book_key(title: str, author: str) -> tuple[str, str]:
    return (" ".join(title.lower().split()), " ".join(author.lower().split()))
