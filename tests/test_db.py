import tempfile
import unittest
from pathlib import Path

from app.db import connect, init_db


class DatabaseMigrationTests(unittest.TestCase):
    def test_init_db_adds_hypothesis_columns_to_existing_recommendations_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            conn.executescript(
                """
                CREATE TABLE recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    book_id INTEGER NOT NULL,
                    recommendation_date TEXT NOT NULL,
                    slot_type TEXT NOT NULL,
                    theme TEXT NOT NULL,
                    recommendation_reason TEXT NOT NULL,
                    profile_mapping TEXT NOT NULL,
                    expected_benefit TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    reading_suggestion TEXT NOT NULL,
                    message_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            init_db(conn)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(recommendations)")}
            conn.close()

        self.assertIn("system_hypothesis", columns)
        self.assertIn("profile_dimensions", columns)

    def test_init_db_adds_reason_code_to_existing_feedback_events_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            conn.executescript(
                """
                CREATE TABLE feedback_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recommendation_id INTEGER NOT NULL,
                    feedback_type TEXT NOT NULL,
                    free_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    processed_at TEXT
                );
                """
            )

            init_db(conn)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(feedback_events)")}
            conn.close()

        self.assertIn("reason_code", columns)

    def test_init_db_creates_reflections_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            init_db(conn)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(reflections)")}
            conn.close()

        self.assertIn("summary", columns)
        self.assertIn("user_md_patch", columns)
        self.assertIn("memory_md_patch", columns)
        self.assertIn("status", columns)

    def test_init_db_creates_reading_pack_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            init_db(conn)
            artifact_columns = {row["name"] for row in conn.execute("PRAGMA table_info(artifacts)")}
            pack_columns = {row["name"] for row in conn.execute("PRAGMA table_info(reading_packs)")}
            source_columns = {row["name"] for row in conn.execute("PRAGMA table_info(book_sources)")}
            link_columns = {row["name"] for row in conn.execute("PRAGMA table_info(reading_pack_sources)")}
            conn.close()

        self.assertIn("path", artifact_columns)
        self.assertIn("sha256", artifact_columns)
        self.assertIn("recommendation_id", pack_columns)
        self.assertIn("artifact_id", pack_columns)
        self.assertIn("content_json", pack_columns)
        self.assertIn("text_excerpt", source_columns)
        self.assertIn("book_source_id", link_columns)


if __name__ == "__main__":
    unittest.main()
