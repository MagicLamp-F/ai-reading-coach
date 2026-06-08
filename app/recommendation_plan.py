from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.repository import Repository

logger = logging.getLogger(__name__)

RECOMMENDATION_PLAN_SCHEMA_VERSION = "recommendation_plan_v1"
RECOMMENDATION_PLAN_ROUTE = "reading.recommend.plan_v1"


class RecommendationPlanService:
    def __init__(self, repo: Repository, library_dir: Path):
        self.repo = repo
        self.library_dir = library_dir

    def run(
        self,
        run_id: int,
        agent: Any,
        profile_context: str,
        recommendation_history_context: str,
    ) -> dict[str, Any] | None:
        planner = getattr(agent, "plan_recommendations", None)
        if not callable(planner):
            return None

        try:
            plan = planner(
                profile_context=profile_context,
                recommendation_history_context=recommendation_history_context,
            )
        except Exception as exc:
            warning = f"recommendation plan failed: {exc}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        if not isinstance(plan, dict):
            warning = "recommendation plan failed: route returned non-object JSON"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        slots = plan.get("slots")
        if not isinstance(slots, list) or not slots:
            warning = "recommendation plan ignored: route returned no usable slots"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return None

        provider = str(getattr(agent, "name", "unknown") or "unknown")
        self.repo.record_cost(
            run_id,
            provider,
            RECOMMENDATION_PLAN_ROUTE,
            1,
            {
                "schema_version": RECOMMENDATION_PLAN_SCHEMA_VERSION,
                "slot_count": len(slots),
                "hint_only": True,
            },
        )
        self._write_artifact(run_id, provider, plan)
        return plan

    def _write_artifact(self, run_id: int, provider: str, plan: dict[str, Any]) -> int:
        now = datetime.now()
        artifact_dir = self.library_dir / "recommendation-plans" / f"{now:%Y}" / f"{now:%m}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{now:%Y-%m-%d}__run-{run_id}__plan.json"
        payload = {
            "schema_version": RECOMMENDATION_PLAN_SCHEMA_VERSION,
            "route": RECOMMENDATION_PLAN_ROUTE,
            "run_id": run_id,
            "hint_only": True,
            "provider": provider,
            "created_at": now.isoformat(timespec="seconds"),
            "plan": plan,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        artifact_path.write_text(raw, encoding="utf-8")
        sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.repo.add_or_update_artifact(
            artifact_type="recommendation_plan",
            title=f"Recommendation plan run {run_id}",
            path=str(artifact_path),
            sha256=sha256,
            content_type="application/json",
            metadata={
                "schema_version": RECOMMENDATION_PLAN_SCHEMA_VERSION,
                "route": RECOMMENDATION_PLAN_ROUTE,
                "run_id": run_id,
                "hint_only": True,
                "provider": provider,
                "slot_count": len(plan.get("slots", [])) if isinstance(plan.get("slots"), list) else 0,
            },
        )
