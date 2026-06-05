import tempfile
import unittest
from pathlib import Path

from app.db import connect, init_db
from app.memory import HermesNativeProfileProvider
from app.metrics import _render_metrics
from app.repository import Repository


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
        self.assertIn('source="snapshot"', metrics)


if __name__ == "__main__":
    unittest.main()
