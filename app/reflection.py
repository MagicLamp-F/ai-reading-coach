from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app.feedback import FEEDBACK_LABELS, FEEDBACK_REASON_LABELS
from app.lark import LarkRobotClient
from app.llm import OpenAIChatClient
from app.profile import PROFILE_CATEGORIES
from app.reflection_adapter import CustomLLMReflectionAdapter, ReflectionAgentAdapter
from app.repository import Repository

logger = logging.getLogger(__name__)


REFLECTION_SYSTEM_PROMPT = (
    "你是 Hermes，阅读私教系统的长期记忆与反思层。"
    "你的任务是基于结构化 SQLite 数据和本周复盘，提出可审计的长期记忆更新建议。"
    "只输出 JSON，不要输出 Markdown 包裹。不要编造没有证据的事实；不确定时写入系统可能误解或反思问题。"
)


class ReflectionError(RuntimeError):
    pass


class HermesReflectionService:
    def __init__(
        self,
        repo: Repository,
        llm: OpenAIChatClient,
        weekly_report_builder: Callable[[], str],
        lark: LarkRobotClient | None = None,
        memory_dir: Path = Path("memory"),
        adapter: ReflectionAgentAdapter | None = None,
    ):
        self.repo = repo
        self.llm = llm
        self.weekly_report_builder = weekly_report_builder
        self.lark = lark
        self.memory_dir = memory_dir
        self.adapter = adapter or CustomLLMReflectionAdapter(llm)

    def generate_reflection(self, days: int = 7, notify_lark: bool = True, auto_apply: bool = False) -> int:
        days = _validated_days(days)
        run_id = self.repo.create_run(
            "hermes_reflection",
            {"days": days, "reflection_adapter": self.adapter.name},
        )
        api_calls = 0
        try:
            ensure_memory_layout(self.memory_dir)
            weekly_report = self.weekly_report_builder()
            context = build_reflection_context(self.repo, days, weekly_report)
            user_prompt = build_reflection_prompt(context)
            result = self.adapter.generate_reflection(REFLECTION_SYSTEM_PROMPT, user_prompt, context)
            response = result.response
            api_calls += result.api_calls
            if not isinstance(response, dict):
                raise ReflectionError("Hermes reflection adapter returned no JSON")

            normalized = normalize_reflection_response(response)
            reflection_id = self.repo.add_reflection(
                period_start=context["period_start"],
                period_end=context["period_end"],
                summary=normalized["summary"],
                accurate_observations=normalized["accurate_observations"],
                misunderstandings=normalized["misunderstandings"],
                profile_updates=normalized["profile_updates"],
                next_questions=normalized["next_questions"],
                user_md_patch=normalized["user_md_patch"],
                memory_md_patch=normalized["memory_md_patch"],
            )
            row = self.repo.get_reflection(reflection_id)
            if row is None:
                raise ReflectionError(f"Reflection insert failed: id={reflection_id}")
            write_reflection_markdown(row, self.memory_dir)

            if auto_apply:
                self.approve_reflection(reflection_id)
                self.apply_reflection(reflection_id, apply_mode="auto")
                row = self.repo.get_reflection(reflection_id)
                if row is None:
                    raise ReflectionError(f"Reflection disappeared after auto apply: id={reflection_id}")
                write_reflection_markdown(row, self.memory_dir)

            if notify_lark:
                self._send_lark_summary(run_id, row)
            for warning in result.warnings:
                self.repo.record_run_warning(run_id, warning)

            self.repo.finish_run(run_id, "success", api_calls=api_calls)
            return reflection_id
        except Exception as exc:
            logger.exception("Hermes reflection generation failed")
            self.repo.finish_run(run_id, "failed", error_message=str(exc), api_calls=api_calls)
            raise

    def approve_reflection(self, reflection_id: int) -> None:
        if self.repo.get_reflection(reflection_id) is None:
            raise ReflectionError(f"Reflection not found: id={reflection_id}")
        if not self.repo.approve_reflection(reflection_id):
            row = self.repo.get_reflection(reflection_id)
            raise ReflectionError(f"Reflection must be draft to approve: id={reflection_id}, status={row['status']}")

    def apply_reflection(self, reflection_id: int, apply_mode: str = "manual") -> Path:
        row = self.repo.get_reflection(reflection_id)
        if row is None:
            raise ReflectionError(f"Reflection not found: id={reflection_id}")
        if row["status"] != "approved":
            raise ReflectionError(f"Reflection must be approved before apply: id={reflection_id}, status={row['status']}")

        ensure_memory_layout(self.memory_dir)
        applied_at = datetime.now().isoformat(timespec="seconds")
        append_patch(self.memory_dir / "USER.md", reflection_id, applied_at, row["user_md_patch"])
        append_patch(self.memory_dir / "MEMORY.md", reflection_id, applied_at, row["memory_md_patch"])
        if not self.repo.mark_reflection_applied(reflection_id):
            raise ReflectionError(f"Reflection apply state update failed: id={reflection_id}")
        applied_row = self.repo.get_reflection(reflection_id)
        if applied_row is None:
            raise ReflectionError(f"Reflection not found after apply: id={reflection_id}")
        return write_reflection_change_log(applied_row, self.memory_dir, apply_mode, applied_at)

    def _send_lark_summary(self, run_id: int, row: Any) -> None:
        if self.lark is None or not self.lark.enabled():
            return
        try:
            message_id = self.lark.send_text(format_lark_reflection_summary(row))
        except Exception as exc:
            warning = f"hermes reflection lark summary failed: {exc}"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)
            return
        if message_id is None:
            warning = "hermes reflection lark summary failed"
            logger.warning(warning)
            self.repo.record_run_warning(run_id, warning)


def ensure_memory_layout(memory_dir: Path = Path("memory")) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "patches").mkdir(parents=True, exist_ok=True)
    (memory_dir / "reflections").mkdir(parents=True, exist_ok=True)
    (memory_dir / "change_logs").mkdir(parents=True, exist_ok=True)
    _ensure_file(memory_dir / "USER.md", "# USER\n\n")
    _ensure_file(memory_dir / "MEMORY.md", "# MEMORY\n\n")


def build_reflection_context(repo: Repository, days: int, weekly_report: str) -> dict[str, Any]:
    days = _validated_days(days)
    now = datetime.now()
    period_start = (now - timedelta(days=days)).date().isoformat()
    period_end = now.date().isoformat()
    recommendations = [_recommendation_context(row) for row in repo.reflection_recommendations(days)]
    feedback_events = [_feedback_context(row) for row in repo.reflection_feedback_events(days)]
    profile_items = [_profile_item_context(row) for row in repo.reflection_profile_items()]
    return {
        "period_start": period_start,
        "period_end": period_end,
        "days": days,
        "recommendations": recommendations,
        "feedback_events": feedback_events,
        "profile_items": profile_items,
        "weekly_report_summary": weekly_report,
        "aggregate_signals": {
            "feedback_type_counts": [_row_dict(row) for row in repo.weekly_feedback_type_counts(days)],
            "reason_code_counts": [_reason_row_dict(row) for row in repo.weekly_reason_code_counts(days)],
            "dimension_counts": [_row_dict(row) for row in repo.weekly_feedback_dimension_counts(days)],
            "positive_theme_counts": [_row_dict(row) for row in repo.weekly_positive_theme_counts(days)],
            "misread_signal_counts": [_reason_row_dict(row) for row in repo.weekly_misread_signal_counts(days)],
        },
    }


def build_reflection_prompt(context: dict[str, Any]) -> str:
    schema = {
        "period_summary": "本周期用户画像摘要，字符串",
        "accurate_observations": ["本周期被反馈支持的准确观察"],
        "long_term_interest_changes": ["用户长期兴趣变化"],
        "short_term_focus_changes": ["短期关注变化"],
        "knowledge_gaps": ["知识缺口"],
        "reading_preferences": ["阅读偏好"],
        "aversion_patterns": ["反感模式"],
        "action_stage": "行动阶段判断",
        "system_misunderstandings": ["系统可能误解"],
        "next_week_strategy": ["下周推荐策略建议"],
        "reflection_questions": ["3-5 个需要用户或系统继续验证的问题"],
        "user_md_patch": "建议追加到 USER.md 的 Markdown patch",
        "memory_md_patch": "建议追加到 MEMORY.md 的 Markdown patch",
    }
    return (
        "请基于以下证据生成 Hermes 反思。输出必须是单个 JSON 对象，并严格包含这些字段：\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        "约束：\n"
        "- USER.md patch 只写稳定或高价值的用户画像更新建议。\n"
        "- MEMORY.md patch 写系统反思、误解修正、下周推荐策略和待验证问题。\n"
        "- patch 不要声明已经应用；是否自动应用由后端控制，并会写审计记录。\n"
        "- 如果证据不足，用保守措辞并放入 reflection_questions。\n\n"
        "证据上下文：\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def normalize_reflection_response(response: dict[str, Any]) -> dict[str, Any]:
    profile_updates = {
        "long_term_interest_changes": _list_value(response, "long_term_interest_changes"),
        "short_term_focus_changes": _list_value(response, "short_term_focus_changes"),
        "knowledge_gaps": _list_value(response, "knowledge_gaps"),
        "reading_preferences": _list_value(response, "reading_preferences"),
        "aversion_patterns": _list_value(response, "aversion_patterns"),
        "action_stage": str(response.get("action_stage", "")).strip(),
        "next_week_strategy": _list_value(response, "next_week_strategy"),
        "deep_profile_reflection": response.get("deep_profile_reflection", response.get("profile_reflection", "")),
    }
    return {
        "summary": _first_text(response, "period_summary", "summary", default="Hermes reflection draft"),
        "accurate_observations": _list_value(response, "accurate_observations", "observations"),
        "misunderstandings": _list_value(response, "system_misunderstandings", "misunderstandings"),
        "profile_updates": profile_updates,
        "next_questions": _list_value(response, "reflection_questions", "next_questions"),
        "user_md_patch": _first_text(response, "user_md_patch", "USER.md patch", default=""),
        "memory_md_patch": _first_text(response, "memory_md_patch", "MEMORY.md patch", default=""),
    }


def write_reflection_markdown(row: Any, memory_dir: Path = Path("memory")) -> Path:
    ensure_memory_layout(memory_dir)
    path = memory_dir / "reflections" / f"reflection_{row['id']}.md"
    content = format_reflection_markdown(row)
    path.write_text(content, encoding="utf-8")
    return path


def write_reflection_change_log(row: Any, memory_dir: Path, apply_mode: str, applied_at: str) -> Path:
    ensure_memory_layout(memory_dir)
    safe_mode = "auto" if apply_mode == "auto" else "manual"
    date_prefix = applied_at[:10]
    path = memory_dir / "change_logs" / f"{date_prefix}_reflection_{row['id']}_{safe_mode}.md"
    content = (
        f"# Reflection Change Log {row['id']}\n\n"
        f"- Mode: {safe_mode}\n"
        f"- Status: {row['status']}\n"
        f"- Applied at: {applied_at}\n"
        f"- Period: {row['period_start']} to {row['period_end']}\n\n"
        "## Summary\n\n"
        f"{row['summary']}\n\n"
        "## USER.md Patch\n\n"
        f"{row['user_md_patch'] or '(empty)'}\n\n"
        "## MEMORY.md Patch\n\n"
        f"{row['memory_md_patch'] or '(empty)'}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def format_reflection_markdown(row: Any) -> str:
    profile_updates = _loads(row["profile_updates_json"], {})
    return (
        f"# Hermes Reflection {row['id']}\n\n"
        f"- Status: {row['status']}\n"
        f"- Period: {row['period_start']} to {row['period_end']}\n"
        f"- Created: {row['created_at']}\n\n"
        "## Summary\n\n"
        f"{row['summary']}\n\n"
        "## Accurate Observations\n\n"
        f"{_markdown_list(_loads(row['accurate_observations_json'], []))}\n\n"
        "## System Misunderstandings\n\n"
        f"{_markdown_list(_loads(row['misunderstandings_json'], []))}\n\n"
        "## Profile Updates\n\n"
        f"```json\n{json.dumps(profile_updates, ensure_ascii=False, indent=2)}\n```\n\n"
        "## Reflection Questions\n\n"
        f"{_markdown_list(_loads(row['next_questions_json'], []))}\n\n"
        "## USER.md Patch\n\n"
        f"{row['user_md_patch'] or '(empty)'}\n\n"
        "## MEMORY.md Patch\n\n"
        f"{row['memory_md_patch'] or '(empty)'}\n"
    )


def format_reflection_show(row: Any) -> str:
    return format_reflection_markdown(row)


def format_reflection_list(rows: list[Any]) -> str:
    if not rows:
        return "No reflections found."
    lines = ["ID | Status | Period | Created | Summary", "-- | -- | -- | -- | --"]
    for row in rows:
        summary = " ".join(str(row["summary"]).split())[:80]
        lines.append(
            f"{row['id']} | {row['status']} | {row['period_start']}..{row['period_end']} | {row['created_at']} | {summary}"
        )
    return "\n".join(lines)


def format_lark_reflection_summary(row: Any) -> str:
    questions = _loads(row["next_questions_json"], [])
    question_lines = _markdown_list(questions[:5])
    if row["status"] == "applied":
        return (
            "Hermes 反思已自动应用\n\n"
            f"reflection_id: {row['id']}\n"
            f"周期: {row['period_start']} 至 {row['period_end']}\n\n"
            f"摘要:\n{row['summary']}\n\n"
            "反思问题:\n"
            f"{question_lines}\n\n"
            "本次 USER.md / MEMORY.md 修改已写入 memory/change_logs。"
        )
    return (
        "Hermes 反思草稿（待人工确认）\n\n"
        f"reflection_id: {row['id']}\n"
        f"周期: {row['period_start']} 至 {row['period_end']}\n\n"
        f"摘要:\n{row['summary']}\n\n"
        "反思问题:\n"
        f"{question_lines}\n\n"
        "请人工确认后再执行 approve-reflection / apply-reflection。"
    )


def append_patch(path: Path, reflection_id: int, applied_at: str, patch: str) -> None:
    normalized_patch = patch.strip() or "(本次 reflection 未提供 patch 内容。)"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n\n## Reflection {reflection_id} Applied {applied_at}\n\n"
            f"{normalized_patch}\n"
        )


def _ensure_file(path: Path, initial_content: str) -> None:
    if not path.exists():
        path.write_text(initial_content, encoding="utf-8")


def _recommendation_context(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "recommendation_date": row["recommendation_date"],
        "book": f"{row['title']} / {row['author']}",
        "slot_type": row["slot_type"],
        "theme": row["theme"],
        "system_hypothesis": row["system_hypothesis"],
        "profile_dimensions": _json_list(row["profile_dimensions"]),
        "recommendation_reason": row["recommendation_reason"],
        "profile_mapping": row["profile_mapping"],
        "expected_benefit": row["expected_benefit"],
        "risk": row["risk"],
        "reading_suggestion": row["reading_suggestion"],
    }


def _feedback_context(row: Any) -> dict[str, Any]:
    reason_code = row["reason_code"]
    return {
        "id": row["id"],
        "recommendation_id": row["recommendation_id"],
        "created_at": row["created_at"],
        "book": f"{row['title']} / {row['author']}",
        "theme": row["theme"],
        "slot_type": row["slot_type"],
        "feedback_type": row["feedback_type"],
        "feedback_label": FEEDBACK_LABELS.get(row["feedback_type"], row["feedback_type"]),
        "reason_code": reason_code,
        "reason_label": FEEDBACK_REASON_LABELS.get(reason_code, reason_code),
        "free_text": row["free_text"],
        "system_hypothesis": row["system_hypothesis"],
        "profile_dimensions": _json_list(row["profile_dimensions"]),
    }


def _profile_item_context(row: Any) -> dict[str, Any]:
    return {
        "category": row["category"],
        "category_label": PROFILE_CATEGORIES.get(row["category"], row["category"]),
        "content": row["content"],
        "weight": float(row["weight"]),
        "confidence": float(row["confidence"]),
        "evidence_count": int(row["evidence_count"]),
        "recent_evidence": _loads(row["evidence_json"], [])[-3:],
        "updated_at": row["updated_at"],
        "last_seen_at": row["last_seen_at"],
    }


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _reason_row_dict(row: Any) -> dict[str, Any]:
    data = _row_dict(row)
    reason_code = data.get("reason_code", "")
    if reason_code:
        data["reason_label"] = FEEDBACK_REASON_LABELS.get(reason_code, reason_code)
    return data


def _json_list(raw: str) -> list[str]:
    parsed = _loads(raw, [])
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def _loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _list_value(response: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = response.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    return []


def _first_text(response: dict[str, Any], *keys: str, default: str) -> str:
    for key in keys:
        value = response.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _markdown_list(items: list[Any]) -> str:
    if not items:
        return "- 暂无"
    return "\n".join(f"- {str(item)}" for item in items)


def _validated_days(days: int) -> int:
    if days < 1 or days > 90:
        raise ValueError("days must be between 1 and 90")
    return days
