from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class RecommendationDraft:
    title: str
    author: str
    source_url: str
    slot_type: str
    theme: str
    recommendation_reason: str
    profile_mapping: str
    system_hypothesis: str
    profile_dimensions: list[str]
    expected_benefit: str
    risk: str
    reading_suggestion: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ReadingPackDraft:
    recommendation_id: int
    book_id: int
    artifact_id: int | None
    status: str
    route: str
    schema_version: str
    title: str
    summary: str
    content: dict[str, Any]
    generator_provider: str
    error_message: str | None = None


@dataclass(frozen=True)
class BookSourceDraft:
    book_id: int
    source_type: str
    url: str
    title: str
    text_excerpt: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RecommendationCandidateDraft:
    run_id: int
    book_id: int
    title: str
    author: str
    source_url: str
    source_provider: str
    candidate_reason: str
    user_fit_score: float
    source_coverage_score: float
    final_score: float
    source_status: str
    status: str
    reject_reason: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class DeliveryOutboxDraft:
    channel: str
    message_type: str
    recommendation_id: int | None
    metadata: dict[str, Any]
    last_error: str = ""
    next_attempt_seconds: int = 0


@dataclass(frozen=True)
class ReadingPlanDraft:
    book_id: int
    source_artifact_id: int | None
    title: str
    source_path: str
    mode: str
    tone: str
    spoiler_policy: str
    plan_days: int
    daily_minutes: int
    lark_push_enabled: bool
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ReadingPlanDayDraft:
    plan_id: int
    day_number: int
    scheduled_date: str
    source_start_char: int
    source_end_char: int
    source_text: str
    estimated_minutes: int
    status: str


@dataclass(frozen=True)
class ReadingDayPackDraft:
    plan_day_id: int
    artifact_id: int | None
    status: str
    route: str
    schema_version: str
    title: str
    content: dict[str, Any]
    generator_provider: str
    error_message: str | None = None


@dataclass(frozen=True)
class ReadingSourceFileDraft:
    book_id: int | None
    artifact_id: int | None
    title: str
    author: str
    original_filename: str
    stored_path: str
    file_format: str
    char_count: int
    sha256: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class HermesProfileUpdateEventDraft:
    feedback_event_id: int
    status: str
    should_update_native_memory: bool
    native_memory_path: str
    memory_entry: str
    rationale: str
    confidence: float
    evidence_summary: str
    error_message: str
    raw_response: dict[str, Any]
    route: str = "reading.feedback.ingest"


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_run(self, run_type: str, metadata: dict[str, Any] | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO run_logs(run_type, status, metadata_json) VALUES (?, ?, ?)",
            (run_type, "running", json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return int(cur.lastrowid)

    def merge_run_metadata(self, run_id: int, metadata_patch: dict[str, Any]) -> None:
        if not metadata_patch:
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT metadata_json FROM run_logs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise LookupError("Run log not found")
            try:
                existing = json.loads(str(row["metadata_json"] or "{}"))
            except json.JSONDecodeError:
                existing = {}
            if not isinstance(existing, dict):
                existing = {}
            existing.update(metadata_patch)
            self.conn.execute(
                """
                UPDATE run_logs
                SET metadata_json = ?
                WHERE id = ?
                """,
                (json.dumps(existing, ensure_ascii=False), run_id),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def finish_run(self, run_id: int, status: str, error_message: str | None = None, api_calls: int = 0) -> None:
        self.conn.execute(
            """
            UPDATE run_logs
            SET status = ?, finished_at = CURRENT_TIMESTAMP, error_message = ?, api_calls = ?
            WHERE id = ?
            """,
            (status, error_message, api_calls, run_id),
        )

    def record_run_warning(self, run_id: int, warning_message: str) -> None:
        self.conn.execute(
            """
            UPDATE run_logs
            SET warning_message = CASE
                WHEN warning_message IS NULL OR warning_message = '' THEN ?
                ELSE warning_message || '\n' || ?
            END
            WHERE id = ?
            """,
            (warning_message, warning_message, run_id),
        )

    def record_cost(self, run_id: int | None, provider: str, operation: str, units: int, metadata: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO cost_logs(run_id, provider, operation, units, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, provider, operation, units, json.dumps(metadata, ensure_ascii=False)),
        )

    def upsert_book(self, title: str, author: str, source_url: str, metadata: dict[str, Any] | None = None) -> int:
        self.conn.execute(
            """
            INSERT INTO books(title, author, source_url, metadata_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(title, author) DO UPDATE SET
                source_url = excluded.source_url,
                metadata_json = excluded.metadata_json
            """,
            (title, author, source_url, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        row = self.conn.execute("SELECT id FROM books WHERE title = ? AND author = ?", (title, author)).fetchone()
        if row is None:
            raise RuntimeError("Book upsert failed")
        return int(row["id"])

    def add_recommendation(self, run_id: int, draft: RecommendationDraft, recommendation_date: date) -> int:
        book_id = self.upsert_book(draft.title, draft.author, draft.source_url, draft.metadata)
        cur = self.conn.execute(
            """
            INSERT INTO recommendations(
                run_id, book_id, recommendation_date, slot_type, theme, recommendation_reason,
                profile_mapping, system_hypothesis, profile_dimensions, expected_benefit, risk, reading_suggestion
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                book_id,
                recommendation_date.isoformat(),
                draft.slot_type,
                draft.theme,
                draft.recommendation_reason,
                draft.profile_mapping,
                draft.system_hypothesis,
                json.dumps(draft.profile_dimensions, ensure_ascii=False),
                draft.expected_benefit,
                draft.risk,
                draft.reading_suggestion,
            ),
        )
        return int(cur.lastrowid)

    def set_recommendation_message_id(self, recommendation_id: int, message_id: str) -> None:
        self.conn.execute(
            "UPDATE recommendations SET message_id = ? WHERE id = ?",
            (message_id, recommendation_id),
        )

    def enqueue_delivery(self, draft: DeliveryOutboxDraft) -> int:
        existing = self.conn.execute(
            """
            SELECT id
            FROM delivery_outbox
            WHERE channel = ?
                AND message_type = ?
                AND COALESCE(recommendation_id, 0) = COALESCE(?, 0)
                AND status = 'pending'
            ORDER BY id DESC
            LIMIT 1
            """,
            (draft.channel, draft.message_type, draft.recommendation_id),
        ).fetchone()
        if existing is not None:
            self.conn.execute(
                """
                UPDATE delivery_outbox
                SET last_error = ?,
                    metadata_json = ?,
                    next_attempt_at = datetime('now', ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    draft.last_error,
                    json.dumps(draft.metadata, ensure_ascii=False),
                    f"+{max(0, draft.next_attempt_seconds)} seconds",
                    int(existing["id"]),
                ),
            )
            return int(existing["id"])

        cur = self.conn.execute(
            """
            INSERT INTO delivery_outbox(
                channel,
                message_type,
                recommendation_id,
                last_error,
                metadata_json,
                next_attempt_at
            )
            VALUES (?, ?, ?, ?, ?, datetime('now', ?))
            """,
            (
                draft.channel,
                draft.message_type,
                draft.recommendation_id,
                draft.last_error,
                json.dumps(draft.metadata, ensure_ascii=False),
                f"+{max(0, draft.next_attempt_seconds)} seconds",
            ),
        )
        return int(cur.lastrowid)

    def pending_deliveries(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT *
                FROM delivery_outbox
                WHERE status = 'pending'
                    AND next_attempt_at <= CURRENT_TIMESTAMP
                ORDER BY next_attempt_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def mark_delivery_sent(self, delivery_id: int) -> None:
        self.conn.execute(
            """
            UPDATE delivery_outbox
            SET status = 'sent',
                sent_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (delivery_id,),
        )

    def mark_delivery_retry(
        self,
        delivery_id: int,
        last_error: str,
        next_attempt_seconds: int,
        max_attempts: int,
    ) -> None:
        self.conn.execute(
            """
            UPDATE delivery_outbox
            SET attempt_count = attempt_count + 1,
                status = CASE WHEN attempt_count + 1 >= ? THEN 'failed' ELSE 'pending' END,
                last_error = ?,
                next_attempt_at = datetime('now', ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                max(1, max_attempts),
                last_error,
                f"+{max(0, next_attempt_seconds)} seconds",
                delivery_id,
            ),
        )

    def add_reading_plan(self, draft: ReadingPlanDraft) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO reading_plans(
                book_id,
                source_artifact_id,
                title,
                source_path,
                mode,
                tone,
                spoiler_policy,
                plan_days,
                daily_minutes,
                lark_push_enabled,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft.book_id,
                draft.source_artifact_id,
                draft.title,
                draft.source_path,
                draft.mode,
                draft.tone,
                draft.spoiler_policy,
                draft.plan_days,
                draft.daily_minutes,
                1 if draft.lark_push_enabled else 0,
                json.dumps(draft.metadata, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)

    def update_reading_plan_config(
        self,
        plan_id: int,
        daily_minutes: int,
        tone: str,
        mode: str,
        spoiler_policy: str,
        lark_push_enabled: bool,
        status: str,
    ) -> bool:
        cur = self.conn.execute(
            """
            UPDATE reading_plans
            SET daily_minutes = ?,
                tone = ?,
                mode = ?,
                spoiler_policy = ?,
                lark_push_enabled = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (daily_minutes, tone, mode, spoiler_policy, 1 if lark_push_enabled else 0, status, plan_id),
        )
        return cur.rowcount > 0

    def add_reading_source_file(self, draft: ReadingSourceFileDraft) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO reading_source_files(
                book_id,
                artifact_id,
                title,
                author,
                original_filename,
                stored_path,
                file_format,
                char_count,
                sha256,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft.book_id,
                draft.artifact_id,
                draft.title,
                draft.author,
                draft.original_filename,
                draft.stored_path,
                draft.file_format,
                draft.char_count,
                draft.sha256,
                json.dumps(draft.metadata, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)

    def list_reading_source_files(self, limit: int = 50, include_deleted: bool = False) -> list[sqlite3.Row]:
        status_filter = "" if include_deleted else "WHERE rsf.status = 'active'"
        return list(
            self.conn.execute(
                f"""
                SELECT rsf.*, b.title AS book_title, b.author AS book_author
                FROM reading_source_files rsf
                LEFT JOIN books b ON b.id = rsf.book_id
                {status_filter}
                ORDER BY rsf.created_at DESC, rsf.id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def get_reading_source_file(self, source_file_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT rsf.*, b.title AS book_title, b.author AS book_author
            FROM reading_source_files rsf
            LEFT JOIN books b ON b.id = rsf.book_id
            WHERE rsf.id = ?
            """,
            (source_file_id,),
        ).fetchone()

    def mark_reading_source_file_deleted(self, source_file_id: int) -> bool:
        cur = self.conn.execute(
            """
            UPDATE reading_source_files
            SET status = 'deleted', updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'active'
            """,
            (source_file_id,),
        )
        return cur.rowcount > 0

    def add_reading_plan_day(self, draft: ReadingPlanDayDraft) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO reading_plan_days(
                plan_id,
                day_number,
                scheduled_date,
                source_start_char,
                source_end_char,
                source_text,
                estimated_minutes,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft.plan_id,
                draft.day_number,
                draft.scheduled_date,
                draft.source_start_char,
                draft.source_end_char,
                draft.source_text,
                draft.estimated_minutes,
                draft.status,
            ),
        )
        return int(cur.lastrowid)

    def add_reading_day_pack(self, draft: ReadingDayPackDraft) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO reading_day_packs(
                plan_day_id,
                artifact_id,
                status,
                route,
                schema_version,
                title,
                content_json,
                generator_provider,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft.plan_day_id,
                draft.artifact_id,
                draft.status,
                draft.route,
                draft.schema_version,
                draft.title,
                json.dumps(draft.content, ensure_ascii=False),
                draft.generator_provider,
                draft.error_message,
            ),
        )
        return int(cur.lastrowid)

    def get_guided_reading_day_page(self, plan_day_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT
                rpd.*,
                rp.title AS plan_title,
                rp.mode,
                rp.tone,
                rp.spoiler_policy,
                rp.plan_days,
                rp.daily_minutes,
                rp.lark_push_enabled,
                b.title AS book_title,
                b.author AS book_author,
                rdp.id AS pack_id,
                rdp.content_json,
                rdp.generator_provider,
                rdp.status AS pack_status,
                a.path AS artifact_path
            FROM reading_plan_days rpd
            JOIN reading_plans rp ON rp.id = rpd.plan_id
            JOIN books b ON b.id = rp.book_id
            LEFT JOIN reading_day_packs rdp ON rdp.plan_day_id = rpd.id
            LEFT JOIN artifacts a ON a.id = rdp.artifact_id
            WHERE rpd.id = ?
            """,
            (plan_day_id,),
        ).fetchone()

    def get_reading_plan_detail(self, plan_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT
                rp.*,
                b.title AS book_title,
                b.author AS book_author,
                a.path AS source_artifact_path
            FROM reading_plans rp
            JOIN books b ON b.id = rp.book_id
            LEFT JOIN artifacts a ON a.id = rp.source_artifact_id
            WHERE rp.id = ?
            """,
            (plan_id,),
        ).fetchone()

    def list_reading_plans(self, limit: int = 30) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT rp.*, b.title AS book_title, b.author AS book_author
                FROM reading_plans rp
                JOIN books b ON b.id = rp.book_id
                ORDER BY rp.created_at DESC, rp.id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def next_lark_push_reading_days(self, limit: int = 10) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT
                    rpd.*,
                    rp.title AS plan_title,
                    rp.mode,
                    rp.tone,
                    rp.spoiler_policy,
                    rp.plan_days,
                    rp.daily_minutes,
                    rp.lark_push_enabled,
                    b.title AS book_title,
                    b.author AS book_author,
                    rdp.content_json
                FROM reading_plan_days rpd
                JOIN reading_plans rp ON rp.id = rpd.plan_id
                JOIN books b ON b.id = rp.book_id
                LEFT JOIN reading_day_packs rdp ON rdp.plan_day_id = rpd.id
                WHERE rp.status = 'active'
                    AND rp.lark_push_enabled = 1
                    AND rpd.status IN ('pending', 'generated')
                    AND (rpd.scheduled_date = '' OR rpd.scheduled_date <= date('now', 'localtime'))
                    AND NOT EXISTS (
                        SELECT 1
                        FROM reading_progress_events rpe
                        WHERE rpe.plan_day_id = rpd.id
                            AND rpe.event_type IN ('lark_push_sent', 'lark_push_skipped_disabled')
                    )
                ORDER BY rpd.scheduled_date ASC, rpd.day_number ASC, rpd.id ASC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def reading_plan_days(self, plan_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT id, day_number, scheduled_date, estimated_minutes, status
                FROM reading_plan_days
                WHERE plan_id = ?
                ORDER BY day_number ASC
                """,
                (plan_id,),
            )
        )

    def add_reading_progress_event(
        self,
        plan_id: int,
        plan_day_id: int | None,
        event_type: str,
        detail: dict[str, Any] | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO reading_progress_events(plan_id, plan_day_id, event_type, detail_json)
            VALUES (?, ?, ?, ?)
            """,
            (plan_id, plan_day_id, event_type, json.dumps(detail or {}, ensure_ascii=False)),
        )
        return int(cur.lastrowid)

    def mark_reading_plan_day_completed(self, plan_day_id: int) -> None:
        self.conn.execute(
            """
            UPDATE reading_plan_days
            SET status = 'completed', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (plan_day_id,),
        )

    def recommendation_exists(self, recommendation_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM recommendations WHERE id = ?",
            (recommendation_id,),
        ).fetchone()
        return row is not None

    def add_feedback(self, recommendation_id: int, feedback_type: str, reason_code: str = "", free_text: str = "") -> int:
        cur = self.conn.execute(
            """
            INSERT INTO feedback_events(recommendation_id, feedback_type, reason_code, free_text)
            VALUES (?, ?, ?, ?)
            """,
            (recommendation_id, feedback_type, reason_code, free_text),
        )
        return int(cur.lastrowid)

    def update_feedback_free_text(self, feedback_id: int, free_text: str) -> bool:
        cur = self.conn.execute(
            "UPDATE feedback_events SET free_text = ? WHERE id = ?",
            (free_text, feedback_id),
        )
        return cur.rowcount > 0

    def unprocessed_feedback(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT f.*, r.theme, r.profile_mapping, r.slot_type, b.title, b.author
                FROM feedback_events f
                JOIN recommendations r ON r.id = f.recommendation_id
                JOIN books b ON b.id = r.book_id
                WHERE f.processed_at IS NULL
                ORDER BY f.created_at ASC, f.id ASC
                """
            )
        )

    def mark_feedback_processed(self, feedback_id: int) -> None:
        self.conn.execute(
            "UPDATE feedback_events SET processed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (feedback_id,),
        )

    def record_hermes_profile_update_event(self, draft: HermesProfileUpdateEventDraft) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO hermes_profile_update_events(
                feedback_event_id, route, status, should_update_native_memory,
                native_memory_path, memory_entry, rationale, confidence,
                evidence_summary, error_message, raw_response_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft.feedback_event_id,
                draft.route,
                draft.status,
                1 if draft.should_update_native_memory else 0,
                draft.native_memory_path,
                draft.memory_entry,
                draft.rationale,
                _clamp(draft.confidence),
                draft.evidence_summary,
                draft.error_message,
                json.dumps(draft.raw_response, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)

    def upsert_profile_item(
        self,
        category: str,
        content: str,
        weight_delta: float,
        confidence_delta: float,
        evidence: dict[str, Any],
    ) -> None:
        existing = self.conn.execute(
            "SELECT * FROM profile_items WHERE category = ? AND content = ?",
            (category, content),
        ).fetchone()
        if existing is None:
            evidence_json = json.dumps([evidence], ensure_ascii=False)
            self.conn.execute(
                """
                INSERT INTO profile_items(category, content, weight, confidence, evidence_count, evidence_json)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    category,
                    content,
                    _clamp(0.5 + weight_delta),
                    _clamp(0.3 + confidence_delta),
                    evidence_json,
                ),
            )
            return

        evidence_list = json.loads(existing["evidence_json"])
        evidence_list.append(evidence)
        evidence_list = evidence_list[-20:]
        self.conn.execute(
            """
            UPDATE profile_items
            SET weight = ?, confidence = ?, evidence_count = evidence_count + 1,
                evidence_json = ?, updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                _clamp(float(existing["weight"]) + weight_delta),
                _clamp(float(existing["confidence"]) + confidence_delta),
                json.dumps(evidence_list, ensure_ascii=False),
                int(existing["id"]),
            ),
        )

    def top_profile_items(self, limit: int = 12) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT * FROM profile_items
                ORDER BY weight DESC, confidence DESC, evidence_count DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def recent_recommendations(self, days: int = 14) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT r.*, b.title, b.author
                FROM recommendations r
                JOIN books b ON b.id = r.book_id
                WHERE r.created_at >= datetime('now', ?)
                ORDER BY r.created_at DESC
                """,
                (f"-{days} days",),
            )
        )

    def reflection_recommendations(self, days: int = 7, limit: int = 80) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT
                    r.id,
                    r.recommendation_date,
                    r.slot_type,
                    r.theme,
                    r.recommendation_reason,
                    r.profile_mapping,
                    r.system_hypothesis,
                    r.profile_dimensions,
                    r.expected_benefit,
                    r.risk,
                    r.reading_suggestion,
                    r.created_at,
                    b.title,
                    b.author
                FROM recommendations r
                JOIN books b ON b.id = r.book_id
                WHERE r.created_at >= datetime('now', ?)
                ORDER BY r.created_at DESC, r.id DESC
                LIMIT ?
                """,
                (f"-{days} days", limit),
            )
        )

    def reflection_feedback_events(self, days: int = 7, limit: int = 120) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT
                    f.id,
                    f.recommendation_id,
                    f.feedback_type,
                    f.reason_code,
                    f.free_text,
                    f.created_at,
                    r.theme,
                    r.slot_type,
                    r.system_hypothesis,
                    r.profile_dimensions,
                    b.title,
                    b.author
                FROM feedback_events f
                JOIN recommendations r ON r.id = f.recommendation_id
                JOIN books b ON b.id = r.book_id
                WHERE f.created_at >= datetime('now', ?)
                ORDER BY f.created_at DESC, f.id DESC
                LIMIT ?
                """,
                (f"-{days} days", limit),
            )
        )

    def get_recommendation_detail(self, recommendation_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT
                r.*,
                b.id AS book_id,
                b.title,
                b.author,
                b.source_url,
                b.metadata_json
            FROM recommendations r
            JOIN books b ON b.id = r.book_id
            WHERE r.id = ?
            """,
            (recommendation_id,),
        ).fetchone()

    def add_or_update_artifact(
        self,
        artifact_type: str,
        title: str,
        path: str,
        sha256: str,
        content_type: str,
        metadata: dict[str, Any],
    ) -> int:
        self.conn.execute(
            """
            INSERT INTO artifacts(artifact_type, title, path, sha256, content_type, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                artifact_type = excluded.artifact_type,
                title = excluded.title,
                sha256 = excluded.sha256,
                content_type = excluded.content_type,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                artifact_type,
                title,
                path,
                sha256,
                content_type,
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        row = self.conn.execute("SELECT id FROM artifacts WHERE path = ?", (path,)).fetchone()
        if row is None:
            raise RuntimeError("Artifact upsert failed")
        return int(row["id"])

    def add_reading_pack(self, draft: ReadingPackDraft) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO reading_packs(
                recommendation_id,
                book_id,
                artifact_id,
                status,
                route,
                schema_version,
                title,
                summary,
                content_json,
                generator_provider,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft.recommendation_id,
                draft.book_id,
                draft.artifact_id,
                draft.status,
                draft.route,
                draft.schema_version,
                draft.title,
                draft.summary,
                json.dumps(draft.content, ensure_ascii=False),
                draft.generator_provider,
                draft.error_message,
            ),
        )
        return int(cur.lastrowid)

    def upsert_book_source(self, draft: BookSourceDraft) -> int:
        self.conn.execute(
            """
            INSERT INTO book_sources(
                book_id,
                source_type,
                url,
                title,
                text_excerpt,
                raw_metadata_json,
                fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(book_id, url) DO UPDATE SET
                source_type = excluded.source_type,
                title = excluded.title,
                text_excerpt = excluded.text_excerpt,
                raw_metadata_json = excluded.raw_metadata_json,
                fetched_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                draft.book_id,
                draft.source_type,
                draft.url,
                draft.title,
                draft.text_excerpt,
                json.dumps(draft.metadata, ensure_ascii=False),
            ),
        )
        row = self.conn.execute(
            "SELECT id FROM book_sources WHERE book_id = ? AND url = ?",
            (draft.book_id, draft.url),
        ).fetchone()
        if row is None:
            raise RuntimeError("Book source upsert failed")
        return int(row["id"])

    def book_sources_for_book(self, book_id: int, limit: int = 5) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT *
                FROM book_sources
                WHERE book_id = ?
                ORDER BY fetched_at DESC, id DESC
                LIMIT ?
                """,
                (book_id, limit),
            )
        )

    def link_reading_pack_sources(self, reading_pack_id: int, book_source_ids: list[int]) -> None:
        for book_source_id in dict.fromkeys(book_source_ids):
            self.conn.execute(
                """
                INSERT OR IGNORE INTO reading_pack_sources(reading_pack_id, book_source_id)
                VALUES (?, ?)
                """,
                (reading_pack_id, book_source_id),
            )

    def reading_pack_sources(self, reading_pack_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT bs.*
                FROM reading_pack_sources rps
                JOIN book_sources bs ON bs.id = rps.book_source_id
                WHERE rps.reading_pack_id = ?
                ORDER BY rps.created_at ASC, bs.id ASC
                """,
                (reading_pack_id,),
            )
        )

    def add_recommendation_candidate(self, draft: RecommendationCandidateDraft) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO recommendation_candidates(
                run_id,
                book_id,
                title,
                author,
                source_url,
                source_provider,
                candidate_reason,
                user_fit_score,
                source_coverage_score,
                final_score,
                source_status,
                status,
                reject_reason,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft.run_id,
                draft.book_id,
                draft.title,
                draft.author,
                draft.source_url,
                draft.source_provider,
                draft.candidate_reason,
                draft.user_fit_score,
                draft.source_coverage_score,
                draft.final_score,
                draft.source_status,
                draft.status,
                draft.reject_reason,
                json.dumps(draft.metadata, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)

    def list_recommendation_candidates(self, run_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT *
                FROM recommendation_candidates
                WHERE run_id = ?
                ORDER BY final_score DESC, id ASC
                """,
                (run_id,),
            )
        )

    def get_reading_pack(self, reading_pack_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT rp.*, a.path AS artifact_path, a.sha256 AS artifact_sha256, b.title AS book_title, b.author AS book_author
            FROM reading_packs rp
            LEFT JOIN artifacts a ON a.id = rp.artifact_id
            JOIN books b ON b.id = rp.book_id
            WHERE rp.id = ?
            """,
            (reading_pack_id,),
        ).fetchone()

    def get_reading_pack_page(self, reading_pack_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT
                rp.*,
                a.path AS artifact_path,
                a.sha256 AS artifact_sha256,
                a.metadata_json AS artifact_metadata_json,
                b.title AS book_title,
                b.author AS book_author,
                r.theme,
                r.recommendation_reason,
                r.system_hypothesis,
                r.expected_benefit,
                r.risk,
                r.reading_suggestion
            FROM reading_packs rp
            LEFT JOIN artifacts a ON a.id = rp.artifact_id
            JOIN books b ON b.id = rp.book_id
            JOIN recommendations r ON r.id = rp.recommendation_id
            WHERE rp.id = ?
            """,
            (reading_pack_id,),
        ).fetchone()

    def list_reading_packs(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT rp.id, rp.recommendation_id, rp.status, rp.title, rp.summary, rp.created_at,
                    a.path AS artifact_path, b.title AS book_title, b.author AS book_author
                FROM reading_packs rp
                LEFT JOIN artifacts a ON a.id = rp.artifact_id
                JOIN books b ON b.id = rp.book_id
                ORDER BY rp.created_at DESC, rp.id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def reflection_profile_items(self, limit: int = 80) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT *
                FROM profile_items
                ORDER BY weight DESC, confidence DESC, evidence_count DESC, updated_at DESC, category ASC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def weekly_feedback_summary(self, days: int = 7) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT f.feedback_type, r.theme, r.slot_type, COUNT(*) AS count
                FROM feedback_events f
                JOIN recommendations r ON r.id = f.recommendation_id
                WHERE f.created_at >= datetime('now', ?)
                GROUP BY f.feedback_type, r.theme, r.slot_type
                ORDER BY count DESC
                """,
                (f"-{days} days",),
            )
        )

    def weekly_recommendation_count(self, days: int = 7) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM recommendations
            WHERE created_at >= datetime('now', ?)
            """,
            (f"-{days} days",),
        ).fetchone()
        return int(row["count"])

    def weekly_feedback_type_counts(self, days: int = 7) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT feedback_type, COUNT(*) AS count
                FROM feedback_events
                WHERE created_at >= datetime('now', ?)
                GROUP BY feedback_type
                ORDER BY count DESC, feedback_type ASC
                """,
                (f"-{days} days",),
            )
        )

    def weekly_reason_code_counts(self, days: int = 7) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT reason_code, COUNT(*) AS count
                FROM feedback_events
                WHERE created_at >= datetime('now', ?) AND reason_code <> ''
                GROUP BY reason_code
                ORDER BY count DESC, reason_code ASC
                """,
                (f"-{days} days",),
            )
        )

    def weekly_feedback_dimension_counts(self, days: int = 7) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT
                    CASE
                        WHEN r.profile_dimensions LIKE '%knowledge_gap%' THEN 'knowledge_gap'
                        WHEN r.slot_type = 'exploration' THEN 'exploration'
                        ELSE 'profile_fit'
                    END AS dimension_type,
                    f.feedback_type,
                    COUNT(*) AS count
                FROM feedback_events f
                JOIN recommendations r ON r.id = f.recommendation_id
                WHERE f.created_at >= datetime('now', ?)
                GROUP BY dimension_type, f.feedback_type
                ORDER BY dimension_type ASC, count DESC, f.feedback_type ASC
                """,
                (f"-{days} days",),
            )
        )

    def weekly_positive_theme_counts(self, days: int = 7) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT r.theme, COUNT(*) AS count
                FROM feedback_events f
                JOIN recommendations r ON r.id = f.recommendation_id
                WHERE f.created_at >= datetime('now', ?)
                    AND f.feedback_type IN ('like', 'go_deeper', 'already_read')
                GROUP BY r.theme
                ORDER BY count DESC, r.theme ASC
                LIMIT 5
                """,
                (f"-{days} days",),
            )
        )

    def weekly_misread_signal_counts(self, days: int = 7) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT f.reason_code, r.theme, COUNT(*) AS count
                FROM feedback_events f
                JOIN recommendations r ON r.id = f.recommendation_id
                WHERE f.created_at >= datetime('now', ?)
                    AND f.feedback_type = 'not_interested'
                    AND f.reason_code <> ''
                GROUP BY f.reason_code, r.theme
                ORDER BY count DESC, f.reason_code ASC, r.theme ASC
                LIMIT 6
                """,
                (f"-{days} days",),
            )
        )

    def recent_profile_updates(self, days: int = 7, limit: int = 8) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT *
                FROM profile_items
                WHERE updated_at >= datetime('now', ?)
                ORDER BY updated_at DESC, weight DESC, confidence DESC, evidence_count DESC
                LIMIT ?
                """,
                (f"-{days} days", limit),
            )
        )

    def profile_items_for_report(self, days: int = 7, limit: int = 40) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT *, created_at >= datetime('now', ?) AS is_recently_created
                FROM profile_items
                ORDER BY weight DESC, confidence DESC, evidence_count DESC, updated_at DESC, category ASC
                LIMIT ?
                """,
                (f"-{days} days", limit),
            )
        )

    def weekly_profile_misunderstanding_signals(self, days: int = 7) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT
                    r.theme,
                    f.feedback_type,
                    f.reason_code,
                    COUNT(*) AS count,
                    COALESCE(negative_totals.negative_count, 0) AS negative_count
                FROM feedback_events f
                JOIN recommendations r ON r.id = f.recommendation_id
                LEFT JOIN (
                    SELECT r2.theme, COUNT(*) AS negative_count
                    FROM feedback_events f2
                    JOIN recommendations r2 ON r2.id = f2.recommendation_id
                    WHERE f2.created_at >= datetime('now', ?)
                        AND f2.feedback_type = 'not_interested'
                    GROUP BY r2.theme
                ) negative_totals ON negative_totals.theme = r.theme
                WHERE f.created_at >= datetime('now', ?)
                    AND (
                        f.feedback_type = 'not_interested'
                        OR f.reason_code IN (
                            'wrong_timing',
                            'topic_irrelevant',
                            'topic_slightly_far',
                            'reason_not_convincing',
                            'need_more_practical',
                            'too_theoretical',
                            'too_marketing'
                        )
                    )
                GROUP BY r.theme, f.feedback_type, f.reason_code
                ORDER BY count DESC, r.theme ASC, f.reason_code ASC
                LIMIT 20
                """,
                (f"-{days} days", f"-{days} days"),
            )
        )

    def recent_feedback_free_texts(self, days: int = 7, limit: int = 3) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT f.free_text, f.feedback_type, f.reason_code, f.created_at, r.theme, b.title, b.author
                FROM feedback_events f
                JOIN recommendations r ON r.id = f.recommendation_id
                JOIN books b ON b.id = r.book_id
                WHERE f.created_at >= datetime('now', ?)
                    AND TRIM(f.free_text) <> ''
                ORDER BY f.created_at DESC, f.id DESC
                LIMIT ?
                """,
                (f"-{days} days", limit),
            )
        )

    def recent_profile_dimension_counts(self, days: int = 7) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT category, COUNT(*) AS item_count, SUM(evidence_count) AS evidence_count, AVG(weight) AS avg_weight
                FROM profile_items
                WHERE updated_at >= datetime('now', ?)
                GROUP BY category
                ORDER BY evidence_count DESC, item_count DESC, category ASC
                LIMIT 8
                """,
                (f"-{days} days",),
            )
        )

    def add_reflection(
        self,
        period_start: str,
        period_end: str,
        summary: str,
        accurate_observations: Any,
        misunderstandings: Any,
        profile_updates: Any,
        next_questions: Any,
        user_md_patch: str,
        memory_md_patch: str,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO reflections(
                period_start,
                period_end,
                summary,
                accurate_observations_json,
                misunderstandings_json,
                profile_updates_json,
                next_questions_json,
                user_md_patch,
                memory_md_patch,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            """,
            (
                period_start,
                period_end,
                summary,
                json.dumps(accurate_observations, ensure_ascii=False),
                json.dumps(misunderstandings, ensure_ascii=False),
                json.dumps(profile_updates, ensure_ascii=False),
                json.dumps(next_questions, ensure_ascii=False),
                user_md_patch,
                memory_md_patch,
            ),
        )
        return int(cur.lastrowid)

    def get_reflection(self, reflection_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM reflections WHERE id = ?",
            (reflection_id,),
        ).fetchone()

    def list_reflections(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT id, period_start, period_end, summary, status, created_at, approved_at, applied_at
                FROM reflections
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def approve_reflection(self, reflection_id: int) -> bool:
        cur = self.conn.execute(
            """
            UPDATE reflections
            SET status = 'approved', approved_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'draft'
            """,
            (reflection_id,),
        )
        return cur.rowcount > 0

    def mark_reflection_applied(self, reflection_id: int) -> bool:
        cur = self.conn.execute(
            """
            UPDATE reflections
            SET status = 'applied', applied_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'approved'
            """,
            (reflection_id,),
        )
        return cur.rowcount > 0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))
