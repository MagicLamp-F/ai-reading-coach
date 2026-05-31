from __future__ import annotations

import hashlib
import json
import logging
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.llm import OpenAIChatClient
from app.memory import DEFAULT_LONG_TERM_MEMORY_MAX_CHARS, load_long_term_memory_context
from app.profile import build_profile_context
from app.repository import ReadingPackDraft, Repository

logger = logging.getLogger(__name__)

FAST_READ_PACK_ROUTE = "reading.fast_read_pack"
FAST_READ_PACK_SCHEMA_VERSION = "fast_read_pack_v1"


class ReadingPackError(RuntimeError):
    pass


class ReadingPackAgentError(RuntimeError):
    pass


class HermesReadingPackAdapter:
    name = "hermes-agent"

    def __init__(
        self,
        command: str = "/home/ubuntu/projects/hermes-agent/bin/reflect-json",
        timeout_seconds: float = 60.0,
        runner=subprocess.run,
    ):
        self.command = command.strip()
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def generate_pack(self, prompt_context: str) -> dict[str, Any]:
        payload = {
            "route": FAST_READ_PACK_ROUTE,
            "domain": "reading",
            "tool_policy": "none",
            "output_schema": FAST_READ_PACK_SCHEMA_VERSION,
            "format": "json",
            "system_prompt": "你是读书私教系统的 Hermes 快速读完包生成器。只输出 JSON object。",
            "user_prompt": (
                "为一本已推荐书生成 fast_read_pack_v1。目标是让用户不用读完全书，也能尽量理解这本书的主张、结构、概念、例子和适合自己的阅读路线。"
                "不要复刻受版权保护的原文，不要声称已经读取了未提供的全文。"
                "如果章节信息不足，明确写成'基于公开信息和推荐上下文的推断性章节地图'。"
                "内容要比推荐理由更深入，避免空泛概述。"
                "输出 JSON 字段：pack_title, copyright_note, source_note, why_recommended, one_sentence_thesis, "
                "problem_statement, core_argument_chain, chapter_map, core_concepts, key_examples, "
                "reading_routes, skip_or_defer, limitations, user_application, self_test_questions。"
                "其中 core_argument_chain、chapter_map、core_concepts、key_examples、skip_or_defer、limitations、self_test_questions 是字符串数组；"
                "reading_routes 是包含 ten_min, thirty_min, two_hour 三个字符串字段的对象。"
            ),
            "context": {"prompt_context": prompt_context},
            "output_contract": {
                "pack_title": "string",
                "copyright_note": "string",
                "source_note": "string",
                "why_recommended": "string",
                "one_sentence_thesis": "string",
                "problem_statement": "string",
                "core_argument_chain": ["string"],
                "chapter_map": ["string"],
                "core_concepts": ["string"],
                "key_examples": ["string"],
                "reading_routes": {"ten_min": "string", "thirty_min": "string", "two_hour": "string"},
                "skip_or_defer": ["string"],
                "limitations": ["string"],
                "user_application": "string",
                "self_test_questions": ["string"],
            },
            "constraints": {
                "do_not_modify_sqlite": True,
                "do_not_send_messages": True,
                "do_not_apply_patches": True,
                "business_orchestrator_writes_outputs": True,
            },
        }
        argv = shlex.split(self.command)
        if not argv:
            raise ReadingPackAgentError("Hermes reading pack command is empty")
        try:
            completed = self.runner(
                argv,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ReadingPackAgentError("Hermes reading pack command not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise ReadingPackAgentError("Hermes reading pack command timed out") from exc

        if completed.returncode != 0:
            stderr_tail = (completed.stderr or "").strip().splitlines()[-1:]
            detail = stderr_tail[0] if stderr_tail else f"exit status {completed.returncode}"
            raise ReadingPackAgentError(f"Hermes reading pack command failed: {detail}")
        try:
            response = json.loads(completed.stdout or "")
        except json.JSONDecodeError as exc:
            raise ReadingPackAgentError("Hermes reading pack command returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise ReadingPackAgentError("Hermes reading pack command returned non-object JSON")
        return response


@dataclass(frozen=True)
class ReadingPackPreview:
    summary: str
    ten_min_route: str
    core_points: tuple[str, ...]
    concepts: tuple[str, ...]
    chapter_items: tuple[str, ...]
    examples: tuple[str, ...]
    limitations: tuple[str, ...]
    artifact_path: str
    status: str


@dataclass(frozen=True)
class ReadingPackResult:
    reading_pack_id: int
    artifact_id: int
    artifact_path: Path
    status: str
    summary: str
    preview: ReadingPackPreview


class FastReadPackService:
    def __init__(
        self,
        repo: Repository,
        llm: OpenAIChatClient,
        memory_dir: Path = Path("memory"),
        library_dir: Path = Path("library"),
        max_memory_chars: int = DEFAULT_LONG_TERM_MEMORY_MAX_CHARS,
        agent: HermesReadingPackAdapter | None = None,
        source_collector: Any | None = None,
    ):
        self.repo = repo
        self.llm = llm
        self.memory_dir = memory_dir
        self.library_dir = library_dir
        self.max_memory_chars = max_memory_chars
        self.agent = agent
        self.source_collector = source_collector

    def generate_for_recommendation(self, recommendation_id: int) -> ReadingPackResult:
        recommendation = self.repo.get_recommendation_detail(recommendation_id)
        if recommendation is None:
            raise ReadingPackError(f"Recommendation not found: id={recommendation_id}")

        sources = self._sources_for_recommendation(recommendation)
        content, status, error_message = self._generate_content(recommendation, sources)
        markdown = render_fast_read_pack_markdown(content)
        artifact_path = self._artifact_path(recommendation)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(markdown, encoding="utf-8")
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        artifact_id = self.repo.add_or_update_artifact(
            artifact_type="reading_pack",
            title=str(content["pack_title"]),
            path=str(artifact_path),
            sha256=digest,
            content_type="text/markdown",
            metadata={
                "route": FAST_READ_PACK_ROUTE,
                "schema_version": FAST_READ_PACK_SCHEMA_VERSION,
                "recommendation_id": recommendation_id,
                "book_id": int(recommendation["book_id"]),
                "status": status,
                "source_ids": _source_ids(sources),
            },
        )
        reading_pack_id = self.repo.add_reading_pack(
            ReadingPackDraft(
                recommendation_id=recommendation_id,
                book_id=int(recommendation["book_id"]),
                artifact_id=artifact_id,
                status=status,
                route=FAST_READ_PACK_ROUTE,
                schema_version=FAST_READ_PACK_SCHEMA_VERSION,
                title=str(content["pack_title"])[:300],
                summary=str(content.get("one_sentence_thesis", ""))[:1000],
                content=content,
                generator_provider=_provider_name(self.llm, self.agent),
                error_message=error_message,
            )
        )
        self.repo.link_reading_pack_sources(reading_pack_id, _source_ids(sources))
        return ReadingPackResult(
            reading_pack_id=reading_pack_id,
            artifact_id=artifact_id,
            artifact_path=artifact_path,
            status=status,
            summary=str(content.get("one_sentence_thesis", "")),
            preview=build_reading_pack_preview(content, artifact_path, status),
        )

    def _generate_content(self, recommendation, sources: list[Any]) -> tuple[dict[str, Any], str, str | None]:
        prompt_context = self._prompt_context(recommendation, sources)
        if self.agent is not None:
            try:
                response = self.agent.generate_pack(prompt_context)
                return _attach_source_refs(normalize_fast_read_pack(response, recommendation), sources), "generated", None
            except Exception as exc:
                logger.exception("Hermes fast read pack generation failed; using fallback pack")
                return self._fallback_content(recommendation, sources), "fallback", str(exc)
        try:
            response = self.llm.complete_json(
                "你是读书私教系统的快速读完包生成器。只输出 JSON object。",
                (
                    "为一本已推荐书生成 fast_read_pack_v1。目标是让用户不用读完全书，也能尽量理解这本书的主张、结构、概念、例子和适合自己的阅读路线。"
                    "不要复刻受版权保护的原文，不要声称已经读取了未提供的全文。"
                    "如果章节信息不足，明确写成'基于公开信息和推荐上下文的推断性章节地图'。"
                    "内容要比推荐理由更深入，避免空泛概述。"
                    "输出 JSON 字段：pack_title, copyright_note, source_note, why_recommended, one_sentence_thesis, "
                    "problem_statement, core_argument_chain, chapter_map, core_concepts, key_examples, "
                    "reading_routes, skip_or_defer, limitations, user_application, self_test_questions。"
                    "其中 core_argument_chain、chapter_map、core_concepts、key_examples、skip_or_defer、limitations、self_test_questions 是字符串数组；"
                    "reading_routes 是包含 ten_min, thirty_min, two_hour 三个字符串字段的对象。\n\n"
                    f"上下文：\n{prompt_context}"
                ),
            )
        except Exception as exc:
            logger.exception("Fast read pack generation failed; using fallback pack")
            return self._fallback_content(recommendation, sources), "fallback", str(exc)

        if not isinstance(response, dict):
            return self._fallback_content(recommendation, sources), "fallback", "model returned no JSON object"
        normalized = normalize_fast_read_pack(response, recommendation)
        return _attach_source_refs(normalized, sources), "generated", None

    def _sources_for_recommendation(self, recommendation) -> list[Any]:
        book_id = int(recommendation["book_id"])
        existing = self.repo.book_sources_for_book(book_id, limit=3)
        if existing:
            return existing
        if self.source_collector is None:
            return []
        self.source_collector.collect_for_recommendation(recommendation)
        return self.repo.book_sources_for_book(book_id, limit=3)

    def _prompt_context(self, recommendation, sources: list[Any] | None = None) -> str:
        memory_context = load_long_term_memory_context(self.memory_dir, self.max_memory_chars)
        profile_context = _build_daily_profile_context(build_profile_context(self.repo), memory_context)
        metadata = _json_loads(recommendation["metadata_json"], {})
        return (
            f"route: {FAST_READ_PACK_ROUTE}\n"
            f"schema_version: {FAST_READ_PACK_SCHEMA_VERSION}\n\n"
            "Book:\n"
            f"- title: {recommendation['title']}\n"
            f"- author: {recommendation['author']}\n"
            f"- source_url: {recommendation['source_url']}\n"
            f"- metadata: {json.dumps(metadata, ensure_ascii=False)}\n\n"
            "Recommendation:\n"
            f"- id: {recommendation['id']}\n"
            f"- date: {recommendation['recommendation_date']}\n"
            f"- theme: {recommendation['theme']}\n"
            f"- slot_type: {recommendation['slot_type']}\n"
            f"- recommendation_reason: {recommendation['recommendation_reason']}\n"
            f"- profile_mapping: {recommendation['profile_mapping']}\n"
            f"- system_hypothesis: {recommendation['system_hypothesis']}\n"
            f"- expected_benefit: {recommendation['expected_benefit']}\n"
            f"- risk: {recommendation['risk']}\n"
            f"- reading_suggestion: {recommendation['reading_suggestion']}\n\n"
            "Book source excerpts:\n"
            f"{_format_source_context(sources or [])}\n\n"
            f"User profile context:\n{profile_context}"
        )

    def _fallback_content(self, recommendation, sources: list[Any] | None = None) -> dict[str, Any]:
        title = str(recommendation["title"])
        author = str(recommendation["author"])
        source_note = (
            f"主要来源：推荐记录和 {len(sources)} 条已采集公开来源。"
            if sources
            else f"主要来源：推荐记录；公开链接：{recommendation['source_url'] or '暂无'}。"
        )
        return _attach_source_refs(
            normalize_fast_read_pack(
            {
                "pack_title": f"{title} 快速读完包",
                "copyright_note": "未读取或复刻全书正文；此版本基于推荐记录、公开链接和已有用户画像生成。",
                "source_note": source_note,
                "why_recommended": str(recommendation["recommendation_reason"]),
                "one_sentence_thesis": f"这本书暂时需要人工补充更完整来源；当前可先围绕“{recommendation['theme']}”理解它和你的目标的关系。",
                "problem_statement": str(recommendation["expected_benefit"] or recommendation["profile_mapping"]),
                "core_argument_chain": [
                    str(recommendation["system_hypothesis"] or "系统认为这本书可验证一个用户画像假设。"),
                    str(recommendation["expected_benefit"] or "它可能帮助你补齐当前阅读目标中的一个缺口。"),
                    str(recommendation["risk"] or "需要后续用更完整书籍材料校验。"),
                ],
                "chapter_map": [
                    "缺少可靠目录来源；下一版应接入合法目录、样章、作者访谈或用户上传材料。",
                    str(recommendation["reading_suggestion"] or "先按推荐中的阅读建议选择重点部分。"),
                ],
                "core_concepts": [str(recommendation["theme"])],
                "key_examples": ["当前版本未获得足够案例来源，建议后续补公开书评或样章后再生成案例层。"],
                "reading_routes": {
                    "ten_min": "先看推荐理由、核心论证链和风险，判断是否值得继续。",
                    "thirty_min": "补充目录或公开书评后，按章节地图扫一遍主要结构。",
                    "two_hour": str(recommendation["reading_suggestion"] or "选择与你当前目标最相关的章节精读。"),
                },
                "skip_or_defer": [str(recommendation["risk"] or "暂缓阅读与当前目标无关的部分。")],
                "limitations": ["这是 fallback 版本，内容深度受限；不应当视为完整读书笔记。"],
                "user_application": str(recommendation["profile_mapping"]),
                "self_test_questions": [
                    "这本书最可能解决我的哪个真实问题？",
                    "推荐理由里哪个假设需要我验证？",
                    "我现在是需要理论、案例还是行动步骤？",
                    "这本书可能不适合我的原因是什么？",
                    "如果只花 30 分钟，我应该读哪一部分？",
                ],
            },
            recommendation,
            ),
            sources or [],
        )

    def _artifact_path(self, recommendation) -> Path:
        date_text = str(recommendation["recommendation_date"])
        year = date_text[:4]
        month = date_text[5:7]
        slug = _slugify(str(recommendation["title"])) or f"book-{recommendation['book_id']}"
        folder = f"{date_text}__{slug}"
        return self.library_dir / year / month / folder / "reading-pack.md"


def normalize_fast_read_pack(raw: dict[str, Any], recommendation) -> dict[str, Any]:
    title = str(recommendation["title"])
    normalized = {
        "schema_version": FAST_READ_PACK_SCHEMA_VERSION,
        "route": FAST_READ_PACK_ROUTE,
        "book": {
            "title": title,
            "author": str(recommendation["author"]),
            "source_url": str(recommendation["source_url"]),
            "recommendation_id": int(recommendation["id"]),
            "book_id": int(recommendation["book_id"]),
        },
        "pack_title": _text(raw.get("pack_title")) or f"{title} 快速读完包",
        "copyright_note": _text(raw.get("copyright_note")) or "本导读不复刻全书正文；优先基于合法公开信息、推荐上下文和模型综合生成。",
        "source_note": _text(raw.get("source_note")) or "来源包括推荐记录、书籍公开链接和当前用户画像上下文。",
        "why_recommended": _text(raw.get("why_recommended")) or str(recommendation["recommendation_reason"]),
        "one_sentence_thesis": _text(raw.get("one_sentence_thesis")) or str(recommendation["expected_benefit"]),
        "problem_statement": _text(raw.get("problem_statement")) or str(recommendation["profile_mapping"]),
        "core_argument_chain": _list(raw.get("core_argument_chain")),
        "chapter_map": _list(raw.get("chapter_map")),
        "core_concepts": _list(raw.get("core_concepts")),
        "key_examples": _list(raw.get("key_examples")),
        "reading_routes": _routes(raw.get("reading_routes")),
        "skip_or_defer": _list(raw.get("skip_or_defer")),
        "limitations": _list(raw.get("limitations")),
        "user_application": _text(raw.get("user_application")) or str(recommendation["expected_benefit"]),
        "self_test_questions": _list(raw.get("self_test_questions"))[:8],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not normalized["core_argument_chain"]:
        normalized["core_argument_chain"] = [str(recommendation["system_hypothesis"])]
    if not normalized["chapter_map"]:
        normalized["chapter_map"] = [str(recommendation["reading_suggestion"])]
    if not normalized["core_concepts"]:
        normalized["core_concepts"] = [str(recommendation["theme"])]
    if not normalized["self_test_questions"]:
        normalized["self_test_questions"] = ["读完这个导读后，我最想验证哪一个观点？"]
    return normalized


def render_fast_read_pack_markdown(content: dict[str, Any]) -> str:
    book = content["book"]
    routes = content["reading_routes"]
    sections = [
        f"# {content['pack_title']}",
        "",
        "## Book",
        f"- Title: {book['title']}",
        f"- Author: {book['author']}",
        f"- Source: {book['source_url'] or 'N/A'}",
        f"- Recommendation id: {book['recommendation_id']}",
        "",
        "## Why This Book",
        content["why_recommended"],
        "",
        "## One Sentence Thesis",
        content["one_sentence_thesis"],
        "",
        "## Problem The Author Is Solving",
        content["problem_statement"],
        "",
        "## Core Argument Chain",
        _markdown_list(content["core_argument_chain"]),
        "",
        "## Chapter Or Part Map",
        _markdown_list(content["chapter_map"]),
        "",
        "## Core Concepts",
        _markdown_list(content["core_concepts"]),
        "",
        "## Examples And Cases",
        _markdown_list(content["key_examples"]),
        "",
        "## Reading Routes",
        f"- 10 minutes: {routes['ten_min']}",
        f"- 30 minutes: {routes['thirty_min']}",
        f"- 2 hours: {routes['two_hour']}",
        "",
        "## Skip Or Defer",
        _markdown_list(content["skip_or_defer"]),
        "",
        "## Limitations And Opposing Views",
        _markdown_list(content["limitations"]),
        "",
        "## How To Use It",
        content["user_application"],
        "",
        "## Self Test",
        _markdown_numbered(content["self_test_questions"]),
        "",
        "## Source And Copyright Notes",
        f"- {content['source_note']}",
        f"- {content['copyright_note']}",
        "",
        "## Source References",
        _markdown_source_refs(content.get("source_refs")),
        "",
    ]
    return "\n".join(sections)


def build_reading_pack_preview(content: dict[str, Any], artifact_path: Path, status: str) -> ReadingPackPreview:
    routes = _routes(content.get("reading_routes"))
    return ReadingPackPreview(
        summary=_text(content.get("one_sentence_thesis"))[:500],
        ten_min_route=routes["ten_min"][:500],
        core_points=tuple(_list(content.get("core_argument_chain"))[:2]),
        concepts=tuple(_list(content.get("core_concepts"))[:5]),
        chapter_items=tuple(_list(content.get("chapter_map"))[:4]),
        examples=tuple(_list(content.get("key_examples"))[:3]),
        limitations=tuple(_list(content.get("limitations"))[:2]),
        artifact_path=str(artifact_path),
        status=status,
    )


def _attach_source_refs(content: dict[str, Any], sources: list[Any]) -> dict[str, Any]:
    content["source_refs"] = [
        {
            "id": _source_value(source, "id"),
            "source_type": _source_value(source, "source_type"),
            "url": _source_value(source, "url"),
            "title": _source_value(source, "title"),
        }
        for source in sources
    ]
    return content


def _format_source_context(sources: list[Any]) -> str:
    if not sources:
        return "No collected book source excerpts yet. Use recommendation metadata and be explicit about source limitations."
    blocks = []
    for index, source in enumerate(sources[:3], start=1):
        title = _source_value(source, "title") or "Untitled source"
        url = _source_value(source, "url")
        source_type = _source_value(source, "source_type") or "unknown"
        excerpt = _source_value(source, "text_excerpt")[:3000]
        blocks.append(
            "\n".join(
                [
                    f"[source {index}]",
                    f"type: {source_type}",
                    f"title: {title}",
                    f"url: {url}",
                    "excerpt:",
                    excerpt,
                ]
            )
        )
    return "\n\n".join(blocks)


def _source_ids(sources: list[Any]) -> list[int]:
    ids = []
    for source in sources:
        raw_id = _source_value(source, "id")
        if raw_id:
            ids.append(int(raw_id))
    return ids


def _source_value(source: Any, key: str) -> str:
    try:
        value = source[key]
    except (KeyError, TypeError, IndexError):
        value = getattr(source, key, "")
    if value is None:
        return ""
    return str(value)


def build_reading_pack_agent(
    provider: str,
    hermes_agent_command: str,
    hermes_agent_timeout_seconds: float,
) -> HermesReadingPackAdapter | None:
    normalized = provider.strip().lower()
    if normalized in {"", "custom", "legacy", "direct"}:
        return None
    if normalized in {"hermes-agent", "hermes_agent", "hermes"}:
        return HermesReadingPackAdapter(
            command=hermes_agent_command,
            timeout_seconds=hermes_agent_timeout_seconds,
        )
    raise ValueError(f"Unsupported READING_PACK_PROVIDER: {provider}")


def _markdown_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item.strip()) or "- N/A"


def _markdown_numbered(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1) if item.strip()) or "1. N/A"


def _markdown_source_refs(raw: Any) -> str:
    if not isinstance(raw, list) or not raw:
        return "- N/A"
    lines = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source_id = _text(item.get("id"))
        title = _text(item.get("title")) or "Untitled source"
        source_type = _text(item.get("source_type")) or "unknown"
        url = _text(item.get("url"))
        lines.append(f"- #{source_id} [{source_type}] {title}: {url}")
    return "\n".join(lines) or "- N/A"


def _routes(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {
            "ten_min": _text(raw.get("ten_min")) or "先读核心论点和适用场景。",
            "thirty_min": _text(raw.get("thirty_min")) or "扫章节地图、核心概念和案例。",
            "two_hour": _text(raw.get("two_hour")) or "选择最相关章节精读，并回答自测问题。",
        }
    if isinstance(raw, list) and raw:
        route_texts = [_text(item) for item in raw if _text(item).strip()]
        return {
            "ten_min": route_texts[0][:500] if route_texts else "先读核心论点和适用场景。",
            "thirty_min": route_texts[1][:500] if len(route_texts) > 1 else "扫章节地图、核心概念和案例。",
            "two_hour": route_texts[2][:500] if len(route_texts) > 2 else "选择最相关章节精读，并回答自测问题。",
        }
    return {
        "ten_min": "先读核心论点和适用场景。",
        "thirty_min": "扫章节地图、核心概念和案例。",
        "two_hour": "选择最相关章节精读，并回答自测问题。",
    }


def _list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [_text(item)[:1200] for item in raw if _text(item).strip()][:20]
    text = _text(raw)
    return [text[:1200]] if text else []


def _text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict):
        return _dict_text(raw)
    if isinstance(raw, list):
        return "；".join(_text(item) for item in raw if _text(item).strip())
    return " ".join(str(raw).split())


def _dict_text(raw: dict[str, Any]) -> str:
    patterns = [
        ("claim", "implication"),
        ("part", "main_idea", "read_for"),
        ("concept", "definition", "why_it_matters"),
        ("example", "system_lesson", "application"),
        ("limitation", "explanation"),
        ("route_name", "for_user_goal", "sequence", "output_prompt"),
        ("step", "claim", "implication"),
    ]
    for pattern in patterns:
        if any(key in raw for key in pattern):
            parts = []
            for key in pattern:
                value = raw.get(key)
                if value is None or value == "":
                    continue
                label = {
                    "claim": "观点",
                    "implication": "含义",
                    "part": "部分",
                    "main_idea": "主旨",
                    "read_for": "读法",
                    "concept": "概念",
                    "definition": "定义",
                    "why_it_matters": "意义",
                    "example": "例子",
                    "system_lesson": "系统启发",
                    "application": "应用",
                    "limitation": "局限",
                    "explanation": "说明",
                    "route_name": "路线",
                    "for_user_goal": "目标",
                    "sequence": "步骤",
                    "output_prompt": "输出问题",
                    "step": "步骤",
                }.get(key, key)
                parts.append(f"{label}: {_text(value)}")
            return "；".join(parts)
    return "；".join(f"{key}: {_text(value)}" for key, value in raw.items() if value not in (None, ""))


def _json_loads(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except json.JSONDecodeError:
        return default


def _build_daily_profile_context(structured_profile_context: str, long_term_memory_context: str) -> str:
    return (
        "SQLite structured profile:\n"
        f"{structured_profile_context.strip() or '暂无画像。'}\n\n"
        "Hermes long-term memory:\n"
        f"{long_term_memory_context.strip() or '暂无 Hermes long-term memory。'}"
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value.strip()).strip("-").lower()
    return slug[:80]


def _provider_name(llm: OpenAIChatClient, agent: HermesReadingPackAdapter | None = None) -> str:
    if agent is not None:
        return agent.name
    model = getattr(llm, "model", "")
    if getattr(llm, "api_key", ""):
        return f"openai-compatible:{model}" if model else "openai-compatible"
    return "fallback:no-api-key"
