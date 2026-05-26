import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.backup import backup_sqlite_database


class BackupTests(unittest.TestCase):
    def test_backup_sqlite_database_creates_readable_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "reading_coach.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
            conn.execute("INSERT INTO sample(name) VALUES (?)", ("first",))
            conn.commit()
            conn.close()

            backup_path = backup_sqlite_database(
                db_path,
                root / "backups",
                timestamp=datetime(2026, 5, 26, 8, 0, 0),
            )

            self.assertEqual(backup_path.name, "reading_coach_20260526_080000.db")
            backup_conn = sqlite3.connect(backup_path)
            try:
                row = backup_conn.execute("SELECT name FROM sample WHERE id = 1").fetchone()
            finally:
                backup_conn.close()
            self.assertEqual(row[0], "first")

    def test_backup_sqlite_database_keeps_latest_fourteen_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "reading_coach.db"
            sqlite3.connect(db_path).close()
            backup_dir = root / "backups"
            backup_dir.mkdir()
            base = datetime(2026, 5, 1, 8, 0, 0)
            for index in range(16):
                path = backup_dir / f"reading_coach_202605{index + 1:02d}_080000.db"
                path.write_text("old", encoding="utf-8")
                ts = time.mktime((base + timedelta(days=index)).timetuple())
                path.touch()
                path.chmod(0o600)
                import os

                os.utime(path, (ts, ts))

            backup_sqlite_database(
                db_path,
                backup_dir,
                keep=14,
                timestamp=datetime(2026, 5, 26, 8, 0, 0),
            )

            backups = sorted(path.name for path in backup_dir.glob("reading_coach_*.db"))
            self.assertEqual(len(backups), 14)
            self.assertIn("reading_coach_20260526_080000.db", backups)
            self.assertNotIn("reading_coach_20260501_080000.db", backups)
            self.assertNotIn("reading_coach_20260502_080000.db", backups)
            self.assertNotIn("reading_coach_20260503_080000.db", backups)


if __name__ == "__main__":
    unittest.main()
