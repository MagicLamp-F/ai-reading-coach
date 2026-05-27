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


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_run(self, run_type: str, metadata: dict[str, Any] | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO run_logs(run_type, status, metadata_json) VALUES (?, ?, ?)",
            (run_type, "running", json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return int(cur.lastrowid)

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
