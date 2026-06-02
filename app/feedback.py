from __future__ import annotations

import base64
import hashlib
import hmac
from urllib.parse import urlencode


FEEDBACK_TYPES = {"like", "neutral", "not_interested", "already_read", "go_deeper"}
FEEDBACK_LABELS = {
    "like": "喜欢",
    "neutral": "一般",
    "not_interested": "不感兴趣",
    "already_read": "已读",
    "go_deeper": "想深入",
}
FEEDBACK_REASONS = {
    "like": [
        "topic_matches",
        "solves_current_problem",
        "useful_methodology",
        "good_difficulty",
        "sparked_new_question",
    ],
    "neutral": [
        "direction_ok_book_not",
        "topic_slightly_far",
        "not_urgent",
        "reason_not_convincing",
        "need_more_practical",
    ],
    "not_interested": [
        "topic_irrelevant",
        "already_know",
        "too_shallow",
        "too_hard",
        "too_theoretical",
        "wrong_timing",
        "too_marketing",
    ],
    "already_read": [
        "already_finished",
        "familiar_with_topic",
        "know_enough",
    ],
    "go_deeper": [
        "current_priority",
        "knowledge_gap",
        "want_reading_path",
        "want_practical_cases",
    ],
}
FEEDBACK_REASON_LABELS = {
    "topic_matches": "主题很匹配",
    "solves_current_problem": "解决当前问题",
    "useful_methodology": "方法论有用",
    "good_difficulty": "难度合适",
    "sparked_new_question": "激发了新问题",
    "direction_ok_book_not": "方向可以但书不合适",
    "topic_slightly_far": "主题略远",
    "not_urgent": "暂时不急",
    "reason_not_convincing": "推荐理由不够有说服力",
    "need_more_practical": "需要更实战",
    "topic_irrelevant": "主题不相关",
    "already_know": "已经掌握",
    "too_shallow": "太浅",
    "too_hard": "太难",
    "too_theoretical": "太理论",
    "wrong_timing": "时机不对",
    "too_marketing": "营销味太重",
    "already_finished": "已经读完",
    "familiar_with_topic": "熟悉这个主题",
    "know_enough": "了解程度已足够",
    "current_priority": "当前优先级",
    "knowledge_gap": "明确知识缺口",
    "want_reading_path": "想要阅读路径",
    "want_practical_cases": "想要实践案例",
}


def sign_feedback(recommendation_id: int, feedback_type: str, secret: str, reason_code: str = "") -> str:
    if feedback_type not in FEEDBACK_TYPES:
        raise ValueError("invalid feedback_type")
    if reason_code and reason_code not in FEEDBACK_REASONS[feedback_type]:
        raise ValueError("invalid reason_code")
    if not secret:
        raise ValueError("FEEDBACK_SECRET is required")
    message_parts = [str(recommendation_id), feedback_type]
    if reason_code:
        message_parts.append(reason_code)
    message = ":".join(message_parts).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_feedback_signature(recommendation_id: int, feedback_type: str, token: str, secret: str, reason_code: str = "") -> bool:
    if feedback_type not in FEEDBACK_TYPES or not token or not secret:
        return False
    if reason_code and reason_code not in FEEDBACK_REASONS[feedback_type]:
        return False
    expected = sign_feedback(recommendation_id, feedback_type, secret, reason_code)
    return hmac.compare_digest(expected, token)


def sign_feedback_free_text(feedback_id: int, secret: str) -> str:
    if not secret:
        raise ValueError("FEEDBACK_SECRET is required")
    message = f"feedback_free_text:{feedback_id}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_feedback_free_text_signature(feedback_id: int, token: str, secret: str) -> bool:
    if not token or not secret:
        return False
    expected = sign_feedback_free_text(feedback_id, secret)
    return hmac.compare_digest(expected, token)


def sign_reading_pack(reading_pack_id: int, secret: str) -> str:
    if not secret:
        raise ValueError("FEEDBACK_SECRET is required")
    message = f"reading_pack:{reading_pack_id}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_reading_pack_signature(reading_pack_id: int, token: str, secret: str) -> bool:
    if not token or not secret:
        return False
    expected = sign_reading_pack(reading_pack_id, secret)
    return hmac.compare_digest(expected, token)


def build_feedback_url(base_url: str, recommendation_id: int, feedback_type: str, secret: str, reason_code: str = "") -> str:
    params = {
        "recommendation_id": str(recommendation_id),
        "feedback_type": feedback_type,
        "token": sign_feedback(recommendation_id, feedback_type, secret, reason_code),
    }
    if reason_code:
        params["reason_code"] = reason_code
    query = urlencode(params)
    return f"{base_url.rstrip('/')}/feedback?{query}"


def build_reading_pack_url(base_url: str, reading_pack_id: int, secret: str) -> str:
    params = {
        "id": str(reading_pack_id),
        "token": sign_reading_pack(reading_pack_id, secret),
    }
    return f"{base_url.rstrip('/')}/reading-pack?{urlencode(params)}"
