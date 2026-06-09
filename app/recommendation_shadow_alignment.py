from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.repository import Repository

SHADOW_COMPARISON_ARTIFACT_TYPE = "recommendation_shadow_comparison"
SHADOW_FEEDBACK_ALIGNMENT_ARTIFACT_TYPE = "recommendation_shadow_feedback_alignment"
SHADOW_FEEDBACK_ALIGNMENT_SCHEMA_VERSION = "recommendation_shadow_feedback_alignment_v1"

POSITIVE_FEEDBACK_TYPES = {"like", "go_deeper", "already_read"}
NEGATIVE_FEEDBACK_TYPES = {"not_interested"}


class RecommendationShadowFeedbackAlignmentService:
    def __init__(self, repo: Repository, library_dir: Path):
        self.repo = repo
        self.library_dir = library_dir

    def align_recent(self, days: int = 30, limit: int = 50) -> dict[str, Any]:
        days = max(1, min(int(days), 365))
        limit = max(1, min(int(limit), 500))
        comparisons = self._recent_comparison_artifacts(days=days, limit=limit)
        alignments = []
        skipped = []
        for artifact in comparisons:
            loaded = _load_json_file(Path(str(artifact["path"])))
            if not isinstance(loaded, dict):
                skipped.append({"artifact_id": int(artifact["id"]), "path": str(artifact["path"]), "reason": "invalid_json"})
                continue
            alignment = self._align_comparison(loaded)
            if alignment is None:
                skipped.append({"artifact_id": int(artifact["id"]), "path": str(artifact["path"]), "reason": "missing_run_id"})
                continue
            alignment["comparison_artifact_id"] = int(artifact["id"])
            alignment["comparison_artifact_path"] = str(artifact["path"])
            alignments.append(alignment)

        artifact_id = self._write_alignment_artifact(
            days=days,
            limit=limit,
            alignments=alignments,
            skipped=skipped,
        )
        return {
            "artifact_id": artifact_id,
            "comparison_count": len(comparisons),
            "aligned_count": len(alignments),
            "skipped_count": len(skipped),
            "ready_count": sum(1 for item in alignments if item["feedback_alignment"]["status"] == "ready"),
            "pending_count": sum(1 for item in alignments if item["feedback_alignment"]["status"] == "pending_future_feedback"),
        }

    def _recent_comparison_artifacts(self, days: int, limit: int) -> list[Any]:
        return list(
            self.repo.conn.execute(
                """
                SELECT *
                FROM artifacts
                WHERE artifact_type = ?
                    AND created_at >= datetime('now', ?)
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (SHADOW_COMPARISON_ARTIFACT_TYPE, f"-{days} days", limit),
            )
        )

    def _align_comparison(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        run_id = _int_value(payload.get("run_id"), 0)
        comparison = payload.get("comparison")
        if not isinstance(comparison, dict):
            comparison = {}
        if run_id <= 0:
            run_id = _int_value(comparison.get("run_id"), 0)
        if run_id <= 0:
            return None

        baseline_feedback = self._feedback_for_run(run_id)
        baseline_summary = _feedback_summary(baseline_feedback)
        feedback_alignment = comparison.get("feedback_alignment")
        if not isinstance(feedback_alignment, dict):
            feedback_alignment = {}
        shadow_keys = [str(item) for item in feedback_alignment.get("shadow_book_keys", []) if str(item).strip()]
        shadow_feedback = self._feedback_for_book_keys(shadow_keys)
        shadow_summary = _feedback_summary(shadow_feedback)
        return {
            "run_id": run_id,
            "baseline": {
                "book_count": _int_value(comparison.get("baseline", {}).get("count") if isinstance(comparison.get("baseline"), dict) else None, 0),
                "feedback": baseline_summary,
            },
            "shadow": {
                "book_count": _int_value(comparison.get("shadow", {}).get("count") if isinstance(comparison.get("shadow"), dict) else None, 0),
                "historical_feedback": shadow_summary,
            },
            "comparison_metrics": comparison.get("comparison") if isinstance(comparison.get("comparison"), dict) else {},
            "feedback_alignment": {
                "status": "ready" if baseline_summary["total"] > 0 else "pending_future_feedback",
                "baseline_outcome": baseline_summary["outcome"],
                "shadow_historical_outcome": shadow_summary["outcome"],
                "baseline_feedback_count": baseline_summary["total"],
                "shadow_historical_feedback_count": shadow_summary["total"],
                "note": (
                    "Baseline feedback is direct delivered-recommendation feedback; "
                    "shadow feedback is only historical title/author feedback unless the same book was also delivered."
                ),
            },
        }

    def _feedback_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.repo.conn.execute(
            """
            SELECT
                f.id,
                f.feedback_type,
                f.reason_code,
                f.free_text,
                f.created_at,
                r.id AS recommendation_id,
                b.title,
                b.author
            FROM feedback_events f
            JOIN recommendations r ON r.id = f.recommendation_id
            JOIN books b ON b.id = r.book_id
            WHERE r.run_id = ?
            ORDER BY f.created_at ASC, f.id ASC
            """,
            (run_id,),
        )
        return [_row_to_feedback(row) for row in rows]

    def _feedback_for_book_keys(self, book_keys: list[str]) -> list[dict[str, Any]]:
        if not book_keys:
            return []
        rows = self.repo.conn.execute(
            """
            SELECT
                f.id,
                f.feedback_type,
                f.reason_code,
                f.free_text,
                f.created_at,
                r.id AS recommendation_id,
                r.run_id,
                b.title,
                b.author
            FROM feedback_events f
            JOIN recommendations r ON r.id = f.recommendation_id
            JOIN books b ON b.id = r.book_id
            ORDER BY f.created_at DESC, f.id DESC
            LIMIT 1000
            """
        )
        wanted = set(book_keys)
        return [_row_to_feedback(row) for row in rows if _book_key(str(row["title"]), str(row["author"])) in wanted]

    def _write_alignment_artifact(
        self,
        days: int,
        limit: int,
        alignments: list[dict[str, Any]],
        skipped: list[dict[str, Any]],
    ) -> int:
        now = datetime.now()
        artifact_dir = self.library_dir / "shadow-feedback-alignments" / f"{now:%Y}" / f"{now:%m}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{now:%Y-%m-%d}__shadow-feedback-alignment.json"
        payload = {
            "schema_version": SHADOW_FEEDBACK_ALIGNMENT_SCHEMA_VERSION,
            "created_at": now.isoformat(timespec="seconds"),
            "window_days": days,
            "limit": limit,
            "summary": {
                "aligned_count": len(alignments),
                "skipped_count": len(skipped),
                "ready_count": sum(1 for item in alignments if item["feedback_alignment"]["status"] == "ready"),
                "pending_count": sum(
                    1 for item in alignments if item["feedback_alignment"]["status"] == "pending_future_feedback"
                ),
            },
            "alignments": alignments,
            "skipped": skipped,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        artifact_path.write_text(raw, encoding="utf-8")
        sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.repo.add_or_update_artifact(
            artifact_type=SHADOW_FEEDBACK_ALIGNMENT_ARTIFACT_TYPE,
            title="Recommendation shadow feedback alignment",
            path=str(artifact_path),
            sha256=sha256,
            content_type="application/json",
            metadata={
                "schema_version": SHADOW_FEEDBACK_ALIGNMENT_SCHEMA_VERSION,
                "window_days": days,
                "aligned_count": len(alignments),
                "ready_count": sum(1 for item in alignments if item["feedback_alignment"]["status"] == "ready"),
                "pending_count": sum(
                    1 for item in alignments if item["feedback_alignment"]["status"] == "pending_future_feedback"
                ),
            },
        )


def _feedback_summary(feedback: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    positive = 0
    negative = 0
    for item in feedback:
        feedback_type = str(item.get("feedback_type") or "")
        reason_code = str(item.get("reason_code") or "")
        type_counts[feedback_type] = type_counts.get(feedback_type, 0) + 1
        if reason_code:
            reason_counts[reason_code] = reason_counts.get(reason_code, 0) + 1
        if feedback_type in POSITIVE_FEEDBACK_TYPES:
            positive += 1
        elif feedback_type in NEGATIVE_FEEDBACK_TYPES:
            negative += 1
    return {
        "total": len(feedback),
        "positive": positive,
        "negative": negative,
        "neutral": max(0, len(feedback) - positive - negative),
        "outcome": _feedback_outcome(positive, negative, len(feedback)),
        "type_counts": dict(sorted(type_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "events": feedback[:20],
    }


def _feedback_outcome(positive: int, negative: int, total: int) -> str:
    if total <= 0:
        return "none"
    if positive > 0 and negative == 0:
        return "positive"
    if negative > 0 and positive == 0:
        return "negative"
    if positive > 0 and negative > 0:
        return "mixed"
    return "neutral"


def _row_to_feedback(row: Any) -> dict[str, Any]:
    return {
        "feedback_id": int(row["id"]),
        "recommendation_id": int(row["recommendation_id"]),
        "run_id": int(row["run_id"]) if "run_id" in row.keys() else None,
        "title": str(row["title"]),
        "author": str(row["author"]),
        "book_key": _book_key(str(row["title"]), str(row["author"])),
        "feedback_type": str(row["feedback_type"]),
        "reason_code": str(row["reason_code"] or ""),
        "free_text": str(row["free_text"] or "")[:500],
        "created_at": str(row["created_at"]),
    }


def _book_key(title: str, author: str) -> str:
    return f"{title.strip().lower()}::{author.strip().lower()}"


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _int_value(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
