from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.repository import Repository
from app.search import SearchResult

logger = logging.getLogger(__name__)

CANDIDATE_RESEARCH_SCHEMA_VERSION = "candidate_research_v1"
CANDIDATE_RESEARCH_ROUTE = "reading.recommend.candidate_research_v1"


class RecommendationCandidateResearchService:
    def __init__(
        self,
        repo: Repository,
        library_dir: Path,
        enabled: bool | None = None,
    ):
        self.repo = repo
        self.library_dir = library_dir
        self.enabled = _env_bool("ARC_ENABLE_CANDIDATE_RESEARCH", False) if enabled is None else enabled

    def run(
        self,
        run_id: int,
        agent: Any,
        profile_context: str,
        recommendation_history_context: str,
        themes: list[str],
        recommendation_plan: dict[str, Any] | None,
        search_results: list[SearchResult],
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        researcher = getattr(agent, "research_candidates", None)
        if not callable(researcher):
            warning = "candidate research skipped: daily agent does not support reading.recommend.candidate_research_v1"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        try:
            research = researcher(
                profile_context=profile_context,
                recommendation_history_context=recommendation_history_context,
                themes=themes,
                recommendation_plan=recommendation_plan,
                search_results=[_search_result_to_payload(result) for result in search_results],
            )
        except Exception as exc:
            warning = f"candidate research failed: {exc}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        if not isinstance(research, dict):
            warning = "candidate research failed: route returned non-object JSON"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        provider = str(getattr(agent, "name", "unknown") or "unknown")
        dossiers = research.get("candidate_dossiers")
        dossier_count = len(dossiers) if isinstance(dossiers, list) else 0
        self.repo.record_cost(
            run_id,
            provider,
            CANDIDATE_RESEARCH_ROUTE,
            1,
            {
                "schema_version": CANDIDATE_RESEARCH_SCHEMA_VERSION,
                "candidate_dossiers": dossier_count,
                "hint_only": True,
            },
        )
        artifact_id = self._write_artifact(
            run_id=run_id,
            provider=provider,
            themes=themes,
            recommendation_plan=recommendation_plan,
            search_results=search_results,
            research=research,
        )
        return {**research, "artifact_id": artifact_id}

    def _write_artifact(
        self,
        run_id: int,
        provider: str,
        themes: list[str],
        recommendation_plan: dict[str, Any] | None,
        search_results: list[SearchResult],
        research: dict[str, Any],
    ) -> int:
        now = datetime.now()
        artifact_dir = self.library_dir / "candidate-research" / f"{now:%Y}" / f"{now:%m}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{now:%Y-%m-%d}__run-{run_id}__candidate-research.json"
        payload = {
            "schema_version": CANDIDATE_RESEARCH_SCHEMA_VERSION,
            "route": CANDIDATE_RESEARCH_ROUTE,
            "run_id": run_id,
            "hint_only": True,
            "provider": provider,
            "created_at": now.isoformat(timespec="seconds"),
            "themes": themes[:6],
            "recommendation_plan": recommendation_plan or {},
            "search_results": [_search_result_to_payload(result) for result in search_results[:12]],
            "candidate_research": research,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        artifact_path.write_text(raw, encoding="utf-8")
        sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        dossiers = research.get("candidate_dossiers")
        return self.repo.add_or_update_artifact(
            artifact_type="recommendation_candidate_research",
            title=f"Recommendation candidate research run {run_id}",
            path=str(artifact_path),
            sha256=sha256,
            content_type="application/json",
            metadata={
                "schema_version": CANDIDATE_RESEARCH_SCHEMA_VERSION,
                "route": CANDIDATE_RESEARCH_ROUTE,
                "run_id": run_id,
                "hint_only": True,
                "provider": provider,
                "candidate_dossiers": len(dossiers) if isinstance(dossiers, list) else 0,
            },
        )


def _search_result_to_payload(result: SearchResult) -> dict[str, str]:
    return {
        "title": result.title[:300],
        "url": result.url[:500],
        "content": result.content[:1000],
    }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
