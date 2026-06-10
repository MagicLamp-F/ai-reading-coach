from __future__ import annotations

import json
from pathlib import Path
from sqlite3 import Row
from typing import Any
from urllib.parse import urlencode

from app.feedback import FEEDBACK_LABELS, FEEDBACK_REASON_LABELS, FEEDBACK_REASONS, sign_feedback, sign_guided_reading_day


READING_PACK_MODULES = [
    ("overview", "总览", "本书定位、作者项目、核心主张和来源边界。"),
    ("argument", "论证", "完整论证链和心智模型，适合建立全局框架。"),
    ("walkthrough", "章节", "按章节/部分穿过全书结构，知道下一页会展开哪里。"),
    ("concepts-cases", "概念案例", "核心概念卡、案例和可识别的工程信号。"),
    ("application", "应用", "阅读路线、应用手册、局限和行动问题。"),
]


def reading_pack_payload(row: Row, token: str, module: str, feedback_secret: str) -> dict[str, Any]:
    content = _json_loads(row["content_json"], {})
    artifact_metadata = _json_loads(row["artifact_metadata_json"], {})
    module_paths = artifact_metadata.get("module_paths", []) if isinstance(artifact_metadata, dict) else []
    current_module = module if module in {item[0] for item in READING_PACK_MODULES} else "overview"
    current_index = [item[0] for item in READING_PACK_MODULES].index(current_module)
    sections = _reading_pack_sections(content).get(current_module, [])
    return {
        "id": int(row["id"]),
        "recommendation_id": int(row["recommendation_id"]),
        "token": token,
        "title": str(row["title"] or f"{row['book_title']} 快读包"),
        "book": {"title": row["book_title"], "author": row["book_author"] or ""},
        "status": row["status"],
        "generator_provider": row["generator_provider"],
        "artifact_path": row["artifact_path"] or "",
        "recommendation": {
            "theme": row["theme"],
            "reason": row["recommendation_reason"],
            "hypothesis": row["system_hypothesis"],
            "expected_benefit": row["expected_benefit"],
            "risk": row["risk"],
            "reading_suggestion": row["reading_suggestion"],
        },
        "modules": [
            {
                "slug": slug,
                "label": label,
                "description": description,
                "path": module_paths[index] if isinstance(module_paths, list) and index < len(module_paths) else "",
                "active": slug == current_module,
            }
            for index, (slug, label, description) in enumerate(READING_PACK_MODULES)
        ],
        "current_module": current_module,
        "current_index": current_index,
        "progress_percent": round(((current_index + 1) / len(READING_PACK_MODULES)) * 100, 1),
        "sections": sections,
        "feedback_options": _feedback_options(int(row["recommendation_id"]), feedback_secret),
        "quotes": [],
    }


def reading_quote_payload(row: Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "reading_pack_id": int(row["reading_pack_id"]),
        "recommendation_id": int(row["recommendation_id"]),
        "book_id": int(row["book_id"]),
        "book": {"title": row["book_title"], "author": row["book_author"] or ""},
        "reading_pack_title": row["reading_pack_title"] if "reading_pack_title" in row.keys() else "",
        "selected_text": row["selected_text"],
        "note": row["note"] or "",
        "module": row["module"] or "",
        "section_title": row["section_title"] or "",
        "source_surface": row["source_surface"] or "",
        "created_at": row["created_at"],
    }


def guided_day_payload(row: Row, days: list[Row], token: str, feedback_secret: str) -> dict[str, Any]:
    content = _json_loads(row["content_json"], {})
    day_number = int(row["day_number"])
    total_days = int(row["plan_days"])
    return {
        "id": int(row["id"]),
        "plan_id": int(row["plan_id"]),
        "token": token,
        "day_number": day_number,
        "total_days": total_days,
        "progress_percent": round((day_number / max(1, total_days)) * 100, 1),
        "estimated_minutes": int(row["estimated_minutes"]),
        "status": row["status"],
        "mode": row["mode"] or "guided",
        "tone": row["tone"] or "short_video",
        "spoiler_policy": row["spoiler_policy"] or "avoid",
        "book": {"title": row["book_title"], "author": row["book_author"] or ""},
        "artifact_path": row["artifact_path"] or "",
        "content": {
            "hook": content.get("hook") or "今天只读这一小段。",
            "one_question": content.get("one_question") or "这段到底在解决什么问题？",
            "plain_explanation": content.get("plain_explanation") or "",
            "key_points": content.get("key_points") if isinstance(content.get("key_points"), list) else [],
            "reality_connection": content.get("reality_connection") or "",
            "why_it_matters": content.get("why_it_matters") or "",
            "tomorrow_teaser": content.get("tomorrow_teaser") or "",
        },
        "source_paragraphs": _text_paragraphs(row["source_text"] or ""),
        "days": [
            {
                "id": int(day["id"]),
                "day_number": int(day["day_number"]),
                "token": sign_guided_reading_day(int(day["id"]), feedback_secret),
                "scheduled_date": day["scheduled_date"],
                "estimated_minutes": int(day["estimated_minutes"]),
                "status": day["status"],
            }
            for day in days
        ],
    }


def reading_plan_payload(row: Row, days: list[Row] | None = None) -> dict[str, Any]:
    payload = {
        "id": int(row["id"]),
        "title": row["title"],
        "book_title": row["book_title"],
        "book_author": row["book_author"] or "",
        "mode": row["mode"],
        "tone": row["tone"],
        "spoiler_policy": row["spoiler_policy"],
        "plan_days": int(row["plan_days"]),
        "daily_minutes": int(row["daily_minutes"]),
        "lark_push_enabled": bool(int(row["lark_push_enabled"] or 0)),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if days is not None:
        payload["days"] = [
            {
                "id": int(day["id"]),
                "day_number": int(day["day_number"]),
                "scheduled_date": day["scheduled_date"],
                "estimated_minutes": int(day["estimated_minutes"]),
                "status": day["status"],
            }
            for day in days
        ]
    return payload


def source_file_payload(row: Row, include_preview: bool = False) -> dict[str, Any]:
    payload = {
        "id": int(row["id"]),
        "title": row["title"],
        "author": row["author"] or "",
        "original_filename": row["original_filename"],
        "file_format": row["file_format"],
        "status": row["status"],
        "char_count": int(row["char_count"]),
        "sha256": row["sha256"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_preview:
        try:
            payload["preview"] = Path(row["stored_path"]).read_text(encoding="utf-8")[:12000]
        except OSError:
            payload["preview"] = ""
    return payload


def created_plan_payload(plan_id: int, first_day_id: int, token: str) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "first_day_id": first_day_id,
        "first_day_url": f"/guided-reading?{urlencode({'day_id': first_day_id, 'token': token})}",
    }


def _feedback_options(recommendation_id: int, feedback_secret: str) -> list[dict[str, Any]]:
    return [
        {
            "type": feedback_type,
            "label": FEEDBACK_LABELS[feedback_type],
            "reasons": [
                {
                    "code": reason_code,
                    "label": FEEDBACK_REASON_LABELS[reason_code],
                    "token": sign_feedback(recommendation_id, feedback_type, feedback_secret, reason_code),
                }
                for reason_code in FEEDBACK_REASONS[feedback_type]
            ],
        }
        for feedback_type in ("like", "neutral", "not_interested", "already_read", "go_deeper")
    ]


def _reading_pack_sections(content: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        "overview": [
            _section("一句话主张", content.get("one_sentence_thesis")),
            _section("定位", content.get("book_positioning")),
            _section("作者项目", content.get("author_project")),
            _section("来源说明", content.get("source_note")),
        ],
        "argument": [
            _section("论证链", content.get("expanded_argument")),
            _section("心智模型", content.get("mental_model_map")),
        ],
        "walkthrough": [_section("章节 Walkthrough", content.get("part_walkthrough"))],
        "concepts-cases": [
            _section("案例库", content.get("story_case_bank")),
            _section("概念卡", content.get("concept_cards")),
        ],
        "application": [
            _section("跳过原书会错过什么", content.get("what_you_would_miss_if_skipping_full_book")),
            _section("10 分钟路线", content.get("ten_min_absorption_path")),
            _section("30 分钟路线", content.get("thirty_min_absorption_path")),
            _section("2 小时路线", content.get("two_hour_absorption_path")),
            _section("用户应用手册", content.get("user_application_playbook")),
            _section("局限", content.get("limitations")),
        ],
    }


def _section(title: str, value: Any) -> dict[str, Any]:
    if value is None:
        body: list[Any] = []
    elif isinstance(value, list):
        body = value
    else:
        body = [str(value)]
    return {"title": title, "body": body, "minutes": _reading_minutes(json.dumps(body, ensure_ascii=False))}


def _reading_minutes(text: str) -> int:
    return max(1, round(len("".join(text.split())) / 450))


def _text_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default
