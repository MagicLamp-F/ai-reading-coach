from __future__ import annotations

from dataclasses import dataclass

from app.repository import Repository


PROFILE_CATEGORIES = {
    "long_term_interest": "长期兴趣",
    "short_term_interest": "短期关注",
    "knowledge_background": "知识背景",
    "reading_preference": "阅读偏好",
    "disliked_topic": "反感主题",
    "life_context": "生活状态",
    "knowledge_gap": "知识缺口",
    "action_stage": "行动阶段",
}


@dataclass(frozen=True)
class ProfileEffect:
    weight_delta: float
    confidence_delta: float
    target_category: str
    content: str = ""


FEEDBACK_EFFECTS = {
    "like": ProfileEffect(0.12, 0.08, "long_term_interest"),
    "neutral": ProfileEffect(0.03, 0.02, "short_term_interest"),
    "not_interested": ProfileEffect(0.10, 0.07, "disliked_topic"),
    "already_read": ProfileEffect(0.08, 0.08, "knowledge_background"),
    "go_deeper": ProfileEffect(0.15, 0.10, "short_term_interest"),
}


def seed_user_manual(repo: Repository, text: str) -> None:
    chunks = [
        line.strip("- ").strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for chunk in chunks:
        repo.upsert_profile_item(
            category="life_context",
            content=chunk[:240],
            weight_delta=0.05,
            confidence_delta=0.05,
            evidence={"source": "user_manual", "text": chunk[:500]},
        )


def process_feedback(repo: Repository) -> int:
    processed = 0
    for event in repo.unprocessed_feedback():
        effects = _effects_for_event(event)
        if not effects:
            repo.mark_feedback_processed(int(event["id"]))
            processed += 1
            continue

        for effect in effects:
            content = effect.content or _content_for_event(event, effect.target_category)
            repo.upsert_profile_item(
                category=effect.target_category,
                content=content,
                weight_delta=effect.weight_delta,
                confidence_delta=effect.confidence_delta,
                evidence={
                    "source": "feedback",
                    "feedback_type": event["feedback_type"],
                    "reason_code": event["reason_code"],
                    "recommendation_id": int(event["recommendation_id"]),
                    "book": f"{event['title']} {event['author']}".strip(),
                    "theme": event["theme"],
                    "free_text": event["free_text"],
                },
            )
        repo.mark_feedback_processed(int(event["id"]))
        processed += 1
    return processed


def build_profile_context(repo: Repository, limit: int = 12) -> str:
    rows = repo.top_profile_items(limit)
    if not rows:
        return "暂无画像。请优先探索用户近期目标、长期兴趣、阅读禁区和知识缺口。"

    lines = []
    for row in rows:
        category_label = PROFILE_CATEGORIES.get(row["category"], row["category"])
        stable = "稳定" if int(row["evidence_count"]) >= 3 and float(row["confidence"]) >= 0.55 else "待验证"
        lines.append(
            f"- [{category_label}/{stable}] {row['content']} "
            f"(weight={row['weight']}, confidence={row['confidence']}, evidence={row['evidence_count']})"
        )
    return "\n".join(lines)


def _content_for_event(event, category: str) -> str:
    if category == "knowledge_background":
        return f"已读或熟悉：{event['title']} {event['author']}".strip()
    if category == "disliked_topic":
        return f"短期避免：{event['theme']}"
    return str(event["theme"])


def _effects_for_event(event) -> list[ProfileEffect]:
    feedback_type = event["feedback_type"]
    reason_code = event["reason_code"]
    theme = str(event["theme"])
    if feedback_type == "not_interested":
        if reason_code == "already_know":
            return [ProfileEffect(0.08, 0.08, "knowledge_background", f"已掌握：{theme}")]
        if reason_code == "wrong_timing":
            return [ProfileEffect(-0.08, 0.04, "short_term_interest", theme)]
        if reason_code == "too_theoretical":
            return [ProfileEffect(0.12, 0.08, "reading_preference", f"偏好更实战：{theme}")]
        if reason_code == "too_hard":
            return [ProfileEffect(0.10, 0.08, "knowledge_gap", f"需要降低难度：{theme}")]

    if feedback_type == "like":
        if reason_code == "solves_current_problem":
            return [
                ProfileEffect(0.14, 0.09, "action_stage", f"当前正在解决：{theme}"),
                ProfileEffect(0.08, 0.06, "knowledge_gap", f"当前问题相关缺口：{theme}"),
            ]
        if reason_code == "useful_methodology":
            return [ProfileEffect(0.12, 0.08, "reading_preference", f"偏好可复用方法论：{theme}")]

    if feedback_type == "go_deeper" and reason_code == "knowledge_gap":
        return [
            ProfileEffect(0.16, 0.10, "knowledge_gap", theme),
            ProfileEffect(0.12, 0.08, "short_term_interest", theme),
        ]

    if feedback_type == "already_read":
        return [ProfileEffect(0.08, 0.08, "knowledge_background")]

    effect = FEEDBACK_EFFECTS.get(feedback_type)
    return [effect] if effect else []
