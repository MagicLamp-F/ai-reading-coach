from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS profile_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 0.5,
            confidence REAL NOT NULL DEFAULT 0.3,
            evidence_count INTEGER NOT NULL DEFAULT 1,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, content)
        );

        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(title, author)
        );

        CREATE TABLE IF NOT EXISTS run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            error_message TEXT,
            warning_message TEXT,
            api_calls INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            recommendation_date TEXT NOT NULL,
            slot_type TEXT NOT NULL,
            theme TEXT NOT NULL,
            recommendation_reason TEXT NOT NULL,
            profile_mapping TEXT NOT NULL,
            system_hypothesis TEXT NOT NULL DEFAULT '',
            profile_dimensions TEXT NOT NULL DEFAULT '[]',
            expected_benefit TEXT NOT NULL,
            risk TEXT NOT NULL,
            reading_suggestion TEXT NOT NULL,
            message_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(run_id) REFERENCES run_logs(id) ON DELETE CASCADE,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS feedback_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recommendation_id INTEGER NOT NULL,
            feedback_type TEXT NOT NULL,
            reason_code TEXT NOT NULL DEFAULT '',
            free_text TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT,
            FOREIGN KEY(recommendation_id) REFERENCES recommendations(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cost_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            provider TEXT NOT NULL,
            operation TEXT NOT NULL,
            units INTEGER NOT NULL DEFAULT 1,
            estimated_cost REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(run_id) REFERENCES run_logs(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            summary TEXT NOT NULL,
            accurate_observations_json TEXT NOT NULL DEFAULT '[]',
            misunderstandings_json TEXT NOT NULL DEFAULT '[]',
            profile_updates_json TEXT NOT NULL DEFAULT '{}',
            next_questions_json TEXT NOT NULL DEFAULT '[]',
            user_md_patch TEXT NOT NULL DEFAULT '',
            memory_md_patch TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'approved', 'rejected', 'applied')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            approved_at TEXT,
            applied_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_profile_category_weight ON profile_items(category, weight DESC, confidence DESC);
        CREATE INDEX IF NOT EXISTS idx_feedback_unprocessed ON feedback_events(processed_at);
        CREATE INDEX IF NOT EXISTS idx_recommendations_date ON recommendations(recommendation_date);
        CREATE INDEX IF NOT EXISTS idx_cost_logs_run ON cost_logs(run_id);
        CREATE INDEX IF NOT EXISTS idx_reflections_status_created ON reflections(status, created_at DESC);
        """
    )
    _ensure_column(conn, "recommendations", "system_hypothesis", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "recommendations", "profile_dimensions", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "feedback_events", "reason_code", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "run_logs", "warning_message", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
