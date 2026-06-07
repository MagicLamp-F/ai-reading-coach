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

        CREATE TABLE IF NOT EXISTS hermes_profile_update_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_event_id INTEGER NOT NULL,
            route TEXT NOT NULL DEFAULT 'reading.feedback.ingest',
            status TEXT NOT NULL CHECK(status IN ('applied', 'skipped', 'failed')),
            should_update_native_memory INTEGER NOT NULL DEFAULT 0,
            native_memory_path TEXT NOT NULL DEFAULT '',
            memory_entry TEXT NOT NULL DEFAULT '',
            rationale TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0,
            evidence_summary TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            raw_response_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(feedback_event_id) REFERENCES feedback_events(id) ON DELETE CASCADE
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

        CREATE TABLE IF NOT EXISTS artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_type TEXT NOT NULL,
            title TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'text/markdown',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reading_packs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recommendation_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            artifact_id INTEGER,
            status TEXT NOT NULL DEFAULT 'generated' CHECK(status IN ('generated', 'fallback', 'failed')),
            route TEXT NOT NULL DEFAULT 'reading.deep_read_pack',
            schema_version TEXT NOT NULL DEFAULT 'deep_read_pack_v2',
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            content_json TEXT NOT NULL DEFAULT '{}',
            generator_provider TEXT NOT NULL DEFAULT '',
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(recommendation_id) REFERENCES recommendations(id) ON DELETE CASCADE,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
            FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS book_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'official_page',
            url TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            text_excerpt TEXT NOT NULL DEFAULT '',
            raw_metadata_json TEXT NOT NULL DEFAULT '{}',
            fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
            UNIQUE(book_id, url)
        );

        CREATE TABLE IF NOT EXISTS reading_pack_sources (
            reading_pack_id INTEGER NOT NULL,
            book_source_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(reading_pack_id, book_source_id),
            FOREIGN KEY(reading_pack_id) REFERENCES reading_packs(id) ON DELETE CASCADE,
            FOREIGN KEY(book_source_id) REFERENCES book_sources(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS recommendation_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            source_provider TEXT NOT NULL DEFAULT '',
            candidate_reason TEXT NOT NULL DEFAULT '',
            user_fit_score REAL NOT NULL DEFAULT 0,
            source_coverage_score REAL NOT NULL DEFAULT 0,
            final_score REAL NOT NULL DEFAULT 0,
            source_status TEXT NOT NULL DEFAULT 'source_missing',
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'selected', 'rejected')),
            reject_reason TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(run_id) REFERENCES run_logs(id) ON DELETE CASCADE,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS delivery_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            message_type TEXT NOT NULL,
            recommendation_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'sent', 'failed')),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(recommendation_id) REFERENCES recommendations(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reading_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            source_artifact_id INTEGER,
            title TEXT NOT NULL,
            source_path TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT 'guided' CHECK(mode IN ('guided', 'fast_intro', 'deep_read', 'drama')),
            tone TEXT NOT NULL DEFAULT 'short_video' CHECK(tone IN ('short_video', 'coach', 'deep', 'drama')),
            spoiler_policy TEXT NOT NULL DEFAULT 'avoid' CHECK(spoiler_policy IN ('avoid', 'allow')),
            plan_days INTEGER NOT NULL DEFAULT 5,
            daily_minutes INTEGER NOT NULL DEFAULT 8,
            lark_push_enabled INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'paused', 'completed', 'archived')),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
            FOREIGN KEY(source_artifact_id) REFERENCES artifacts(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS reading_source_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER,
            artifact_id INTEGER,
            title TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            original_filename TEXT NOT NULL DEFAULT '',
            stored_path TEXT NOT NULL DEFAULT '',
            file_format TEXT NOT NULL DEFAULT 'text',
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'deleted')),
            char_count INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE SET NULL,
            FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS reading_plan_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            day_number INTEGER NOT NULL,
            scheduled_date TEXT NOT NULL DEFAULT '',
            source_start_char INTEGER NOT NULL DEFAULT 0,
            source_end_char INTEGER NOT NULL DEFAULT 0,
            source_text TEXT NOT NULL DEFAULT '',
            estimated_minutes INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'generated', 'completed', 'skipped')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(plan_id) REFERENCES reading_plans(id) ON DELETE CASCADE,
            UNIQUE(plan_id, day_number)
        );

        CREATE TABLE IF NOT EXISTS reading_day_packs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_day_id INTEGER NOT NULL UNIQUE,
            artifact_id INTEGER,
            status TEXT NOT NULL DEFAULT 'generated' CHECK(status IN ('generated', 'fallback', 'failed')),
            route TEXT NOT NULL DEFAULT 'reading.guided_daily_pack',
            schema_version TEXT NOT NULL DEFAULT 'guided_daily_pack_v1',
            title TEXT NOT NULL,
            content_json TEXT NOT NULL DEFAULT '{}',
            generator_provider TEXT NOT NULL DEFAULT 'local-heuristic',
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(plan_day_id) REFERENCES reading_plan_days(id) ON DELETE CASCADE,
            FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS reading_progress_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            plan_day_id INTEGER,
            event_type TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(plan_id) REFERENCES reading_plans(id) ON DELETE CASCADE,
            FOREIGN KEY(plan_day_id) REFERENCES reading_plan_days(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_profile_category_weight ON profile_items(category, weight DESC, confidence DESC);
        CREATE INDEX IF NOT EXISTS idx_feedback_unprocessed ON feedback_events(processed_at);
        CREATE INDEX IF NOT EXISTS idx_hermes_profile_update_feedback ON hermes_profile_update_events(feedback_event_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hermes_profile_update_status ON hermes_profile_update_events(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_recommendations_date ON recommendations(recommendation_date);
        CREATE INDEX IF NOT EXISTS idx_cost_logs_run ON cost_logs(run_id);
        CREATE INDEX IF NOT EXISTS idx_reflections_status_created ON reflections(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_artifacts_type_created ON artifacts(artifact_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reading_packs_recommendation ON reading_packs(recommendation_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reading_packs_book ON reading_packs(book_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_book_sources_book ON book_sources(book_id, fetched_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reading_pack_sources_source ON reading_pack_sources(book_source_id);
        CREATE INDEX IF NOT EXISTS idx_recommendation_candidates_run_score ON recommendation_candidates(run_id, final_score DESC);
        CREATE INDEX IF NOT EXISTS idx_recommendation_candidates_status ON recommendation_candidates(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_delivery_outbox_pending ON delivery_outbox(status, next_attempt_at, id);
        CREATE INDEX IF NOT EXISTS idx_delivery_outbox_recommendation ON delivery_outbox(recommendation_id, status);
        CREATE INDEX IF NOT EXISTS idx_reading_plans_status ON reading_plans(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reading_source_files_status ON reading_source_files(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reading_plan_days_plan ON reading_plan_days(plan_id, day_number);
        CREATE INDEX IF NOT EXISTS idx_reading_day_packs_day ON reading_day_packs(plan_day_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reading_progress_events_plan ON reading_progress_events(plan_id, created_at DESC);
        """
    )
    _ensure_column(conn, "recommendations", "system_hypothesis", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "recommendations", "profile_dimensions", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "feedback_events", "reason_code", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "run_logs", "warning_message", "TEXT")
    _ensure_column(conn, "reading_plans", "lark_push_enabled", "INTEGER NOT NULL DEFAULT 0")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
