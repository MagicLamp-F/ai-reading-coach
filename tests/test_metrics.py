import tempfile
import unittest
from pathlib import Path

from app.db import connect, init_db
from app.memory import HermesNativeProfileProvider
from app.metrics import _render_metrics
from app.repository import HermesProfileUpdateEventDraft, Repository


class MetricsTests(unittest.TestCase):
    def test_metrics_include_hermes_native_profile_load_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "HERMES_NATIVE_PROFILE.md"
            snapshot.write_text("Reading Preferences: source-aware", encoding="utf-8")
            HermesNativeProfileProvider(snapshot_path=snapshot, fallback_soul_path=root / "missing.md").load_context()
            conn = connect(root / "test.db")
            init_db(conn)
            repo = Repository(conn)

            metrics = _render_metrics(repo)

        self.assertIn("reading_coach_hermes_native_profile_loads_total", metrics)
        self.assertIn('source="compat_snapshot"', metrics)

    def test_metrics_include_hermes_profile_update_status_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "test.db")
            init_db(conn)
            repo = Repository(conn)
            rec_id = _add_recommendation(repo)
            feedback_id = repo.add_feedback(rec_id, "like")
            repo.record_hermes_profile_update_event(
                HermesProfileUpdateEventDraft(
                    feedback_event_id=feedback_id,
                    status="applied",
                    should_update_native_memory=True,
                    native_memory_path="/home/ubuntu/.hermes/memories/USER.md",
                    memory_entry="[arc-reading-profile] User reading profile: 偏好工程实战。",
                    rationale="explicit",
                    confidence=0.8,
                    evidence_summary="like",
                    error_message="",
                    raw_response={"should_update_native_memory": True},
                )
            )

            metrics = _render_metrics(repo)
            conn.close()

        self.assertIn("reading_coach_hermes_profile_updates_total", metrics)
        self.assertIn('reading_coach_hermes_profile_updates_total{status="applied"} 1', metrics)


def _add_recommendation(repo: Repository) -> int:
    from app.repository import RecommendationDraft

    run_id = repo.create_run("test")
    return repo.add_recommendation(
        run_id,
        RecommendationDraft(
            title="Metrics Book",
            author="A",
            source_url="",
            slot_type="profile_fit",
            theme="软件工程实践",
            recommendation_reason="r",
            profile_mapping="m",
            system_hypothesis="h",
            profile_dimensions=["reading_preference"],
            expected_benefit="b",
            risk="risk",
            reading_suggestion="s",
            metadata={},
        ),
        __import__("datetime").date.today(),
    )


if __name__ == "__main__":
    unittest.main()
