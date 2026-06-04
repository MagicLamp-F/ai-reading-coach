from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from html import unescape
from xml.etree import ElementTree
from pathlib import Path

from app.repository import ReadingDayPackDraft, ReadingPlanDayDraft, ReadingPlanDraft, ReadingSourceFileDraft, Repository

GUIDED_DAILY_PACK_ROUTE = "reading.guided_daily_pack"
GUIDED_DAILY_PACK_SCHEMA_VERSION = "guided_daily_pack_v1"


class GuidedReadingError(RuntimeError):
    pass


@dataclass(frozen=True)
class GuidedReadingPlanResult:
    plan_id: int
    day_ids: tuple[int, ...]
    first_day_id: int


class GuidedReadingService:
    def __init__(self, repo: Repository, library_dir: Path = Path("library")):
        self.repo = repo
        self.library_dir = library_dir

    def create_plan_from_source(
        self,
        source_path: Path,
        title: str,
        author: str = "",
        plan_days: int = 5,
        daily_minutes: int = 8,
        start_date: date | None = None,
        mode: str = "guided",
        tone: str = "short_video",
        spoiler_policy: str = "avoid",
        lark_push_enabled: bool = False,
    ) -> GuidedReadingPlanResult:
        if plan_days < 1 or plan_days > 60:
            raise GuidedReadingError("plan_days must be between 1 and 60")
        if daily_minutes < 1 or daily_minutes > 180:
            raise GuidedReadingError("daily_minutes must be between 1 and 180")
        if mode not in {"guided", "fast_intro", "deep_read", "drama"}:
            raise GuidedReadingError("invalid reading mode")
        if tone not in {"short_video", "coach", "deep", "drama"}:
            raise GuidedReadingError("invalid reading tone")
        if spoiler_policy not in {"avoid", "allow"}:
            raise GuidedReadingError("invalid spoiler policy")
        if not source_path.is_file():
            raise GuidedReadingError(f"source file not found: {source_path}")

        text = source_path.read_text(encoding="utf-8")
        clean_text = _clean_source_text(text)
        if len(clean_text) < 120:
            raise GuidedReadingError("source text is too short to create a reading plan")

        book_id = self.repo.upsert_book(title=title, author=author, source_url="", metadata={"source_kind": "user_file"})
        artifact_id = self._save_source_artifact(title, source_path, clean_text)
        plan_id = self.repo.add_reading_plan(
            ReadingPlanDraft(
                book_id=book_id,
                source_artifact_id=artifact_id,
                title=title,
                source_path=str(source_path),
                mode=mode,
                tone=tone,
                spoiler_policy=spoiler_policy,
                plan_days=plan_days,
                daily_minutes=daily_minutes,
                lark_push_enabled=lark_push_enabled,
                metadata={"source_sha256": _sha256_text(clean_text), "source_chars": len(clean_text)},
            )
        )

        day_ids: list[int] = []
        chunks = _split_text_for_days(clean_text, plan_days)
        cursor = 0
        first_date = start_date or date.today()
        for index, chunk in enumerate(chunks, start=1):
            start_char = clean_text.find(chunk, cursor)
            if start_char < 0:
                start_char = cursor
            end_char = start_char + len(chunk)
            cursor = end_char
            day_id = self.repo.add_reading_plan_day(
                ReadingPlanDayDraft(
                    plan_id=plan_id,
                    day_number=index,
                    scheduled_date=(first_date + timedelta(days=index - 1)).isoformat(),
                    source_start_char=start_char,
                    source_end_char=end_char,
                    source_text=chunk,
                    estimated_minutes=max(1, round(len(chunk) / 450)),
                    status="generated",
                )
            )
            content = build_guided_daily_pack(
                title=title,
                day_number=index,
                total_days=plan_days,
                source_text=chunk,
                mode=mode,
                tone=tone,
                spoiler_policy=spoiler_policy,
            )
            pack_artifact_id = self._save_day_pack_artifact(title, index, content, chunk)
            self.repo.add_reading_day_pack(
                ReadingDayPackDraft(
                    plan_day_id=day_id,
                    artifact_id=pack_artifact_id,
                    status="generated",
                    route=GUIDED_DAILY_PACK_ROUTE,
                    schema_version=GUIDED_DAILY_PACK_SCHEMA_VERSION,
                    title=f"{title} Day {index} 导读",
                    content=content,
                    generator_provider="local-heuristic",
                )
            )
            day_ids.append(day_id)

        return GuidedReadingPlanResult(plan_id=plan_id, day_ids=tuple(day_ids), first_day_id=day_ids[0])

    def create_plan_from_text(
        self,
        source_text: str,
        title: str,
        author: str = "",
        plan_days: int = 5,
        daily_minutes: int = 8,
        start_date: date | None = None,
        mode: str = "guided",
        tone: str = "short_video",
        spoiler_policy: str = "avoid",
        lark_push_enabled: bool = False,
    ) -> GuidedReadingPlanResult:
        clean_text = _clean_source_text(source_text)
        if len(clean_text) < 120:
            raise GuidedReadingError("source text is too short to create a reading plan")
        safe_title = _slug(title)
        source_path = self.library_dir / "guided-reading" / safe_title / "uploaded-source.md"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(clean_text, encoding="utf-8")
        return self.create_plan_from_source(
            source_path=source_path,
            title=title,
            author=author,
            plan_days=plan_days,
            daily_minutes=daily_minutes,
            start_date=start_date,
            mode=mode,
            tone=tone,
            spoiler_policy=spoiler_policy,
            lark_push_enabled=lark_push_enabled,
        )

    def import_source_file(
        self,
        source_path: Path,
        title: str,
        author: str = "",
        original_filename: str = "",
    ) -> int:
        if not source_path.is_file():
            raise GuidedReadingError(f"source file not found: {source_path}")
        suffix = source_path.suffix.lower()
        if suffix not in {".md", ".txt", ".epub"}:
            raise GuidedReadingError("only .md, .txt, and .epub source files are supported in v1")
        raw = source_path.read_bytes()
        if len(raw) > 10 * 1024 * 1024:
            raise GuidedReadingError("source file is too large; v1 limit is 10MB")
        if suffix == ".epub":
            text = _extract_epub_text(source_path)
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise GuidedReadingError("source file must be UTF-8 encoded") from exc
        clean_text = _clean_source_text(text)
        if len(clean_text) < 120:
            raise GuidedReadingError("source text is too short to import")
        book_id = self.repo.upsert_book(title=title, author=author, source_url="", metadata={"source_kind": "user_file"})
        safe_title = _slug(title)
        filename = original_filename or source_path.name
        stored_path = self.library_dir / "guided-reading" / safe_title / "sources" / _safe_filename(filename)
        stored_path.parent.mkdir(parents=True, exist_ok=True)
        stored_path.write_text(clean_text, encoding="utf-8")
        sha256 = _sha256_text(clean_text)
        artifact_id = self.repo.add_or_update_artifact(
            artifact_type="guided_reading_source",
            title=f"{title} 书源",
            path=str(stored_path),
            sha256=sha256,
            content_type=_source_content_type(suffix),
            metadata={"original_filename": filename, "file_format": suffix.lstrip(".")},
        )
        return self.repo.add_reading_source_file(
            ReadingSourceFileDraft(
                book_id=book_id,
                artifact_id=artifact_id,
                title=title,
                author=author,
                original_filename=filename,
                stored_path=str(stored_path),
                file_format=suffix.lstrip("."),
                char_count=len(clean_text),
                sha256=sha256,
                metadata={},
            )
        )

    def create_plan_from_source_file(
        self,
        source_file_id: int,
        plan_days: int = 5,
        daily_minutes: int = 8,
        start_date: date | None = None,
        mode: str = "guided",
        tone: str = "short_video",
        spoiler_policy: str = "avoid",
        lark_push_enabled: bool = False,
    ) -> GuidedReadingPlanResult:
        row = self.repo.get_reading_source_file(source_file_id)
        if row is None or row["status"] != "active":
            raise GuidedReadingError("source file not found")
        return self.create_plan_from_source(
            source_path=Path(row["stored_path"]),
            title=str(row["title"]),
            author=str(row["author"] or ""),
            plan_days=plan_days,
            daily_minutes=daily_minutes,
            start_date=start_date,
            mode=mode,
            tone=tone,
            spoiler_policy=spoiler_policy,
            lark_push_enabled=lark_push_enabled,
        )

    def _save_source_artifact(self, title: str, source_path: Path, text: str) -> int:
        safe_title = _slug(title)
        artifact_path = self.library_dir / "guided-reading" / safe_title / "source.md"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(text, encoding="utf-8")
        return self.repo.add_or_update_artifact(
            artifact_type="guided_reading_source",
            title=f"{title} 书源",
            path=str(artifact_path),
            sha256=_sha256_text(text),
            content_type="text/markdown",
            metadata={"source_path": str(source_path)},
        )

    def _save_day_pack_artifact(self, title: str, day_number: int, content: dict, source_text: str) -> int:
        safe_title = _slug(title)
        artifact_path = self.library_dir / "guided-reading" / safe_title / f"day-{day_number:02d}" / "guided-pack.md"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        markdown = render_guided_daily_pack_markdown(content, source_text)
        artifact_path.write_text(markdown, encoding="utf-8")
        return self.repo.add_or_update_artifact(
            artifact_type="guided_daily_pack",
            title=f"{title} Day {day_number} 导读",
            path=str(artifact_path),
            sha256=_sha256_text(markdown),
            content_type="text/markdown",
            metadata={"day_number": day_number},
        )


def build_guided_daily_pack(
    title: str,
    day_number: int,
    total_days: int,
    source_text: str,
    mode: str,
    tone: str,
    spoiler_policy: str,
) -> dict:
    paragraphs = _paragraphs(source_text)
    first = paragraphs[0] if paragraphs else source_text[:220]
    keywords = _keywords(source_text)
    core_question = _core_question(mode, keywords)
    return {
        "title": title,
        "day_number": day_number,
        "total_days": total_days,
        "mode": mode,
        "tone": tone,
        "spoiler_policy": spoiler_policy,
        "hook": _hook(mode, tone, first, keywords),
        "why_it_matters": _why_it_matters(mode, keywords),
        "one_question": core_question,
        "source_instruction": "今天只读这一小段。先抓住问题，不要求一次读透。",
        "plain_explanation": _plain_explanation(mode, paragraphs, keywords),
        "key_points": _key_points(paragraphs, keywords),
        "reality_connection": _reality_connection(mode, keywords),
        "after_reading_prompt": _after_reading_prompt(mode),
        "tomorrow_teaser": _tomorrow_teaser(mode, day_number, total_days),
        "estimated_minutes": max(1, round(len(source_text) / 450)),
    }


def render_guided_daily_pack_markdown(content: dict, source_text: str) -> str:
    points = "\n".join(f"- {item}" for item in content.get("key_points", []))
    return (
        f"# {content.get('title', '')} Day {content.get('day_number', '')} 导读\n\n"
        f"## 今日钩子\n\n{content.get('hook', '')}\n\n"
        f"## 为什么和你有关\n\n{content.get('why_it_matters', '')}\n\n"
        f"## 今天只抓一个问题\n\n{content.get('one_question', '')}\n\n"
        f"## 今日原文\n\n{source_text}\n\n"
        f"## 白话拆解\n\n{content.get('plain_explanation', '')}\n\n"
        f"## 关键点\n\n{points}\n\n"
        f"## 明天预告\n\n{content.get('tomorrow_teaser', '')}\n"
    )


def _clean_source_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_text_for_days(text: str, plan_days: int) -> list[str]:
    paragraphs = _paragraphs(text)
    if not paragraphs:
        return [text]
    target = max(1, len(text) // plan_days)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        if current and len(chunks) < plan_days - 1 and current_len + len(paragraph) > target:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_len = 0
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        chunks.append("\n\n".join(current).strip())
    while len(chunks) < plan_days:
        chunks.append("")
    return chunks[:plan_days]


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _keywords(text: str) -> list[str]:
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,8}", text)
    stop = {"这个", "一个", "我们", "他们", "如果", "因为", "所以", "但是", "没有", "不是", "可以", "今天", "作者"}
    seen: dict[str, int] = {}
    for word in candidates:
        if word in stop:
            continue
        seen[word] = seen.get(word, 0) + 1
    return [word for word, _ in sorted(seen.items(), key=lambda item: (-item[1], item[0]))[:5]]


def _hook(mode: str, tone: str, first: str, keywords: list[str]) -> str:
    focus = keywords[0] if keywords else "这段内容"
    if mode == "drama" or tone == "drama":
        return f"上一段先续上：今天不要急着看结局，先盯住“{focus}”怎么推动人物或局势变化。"
    if tone == "coach":
        return f"今天只做一件事：看懂“{focus}”为什么重要。先别追求完整，读完这一小段就够。"
    if tone == "deep":
        return f"今天这段的入口是“{focus}”。先看它如何提出问题，再看作者用什么方式推进判断。"
    teaser = first[:90].replace("\n", " ")
    return f"今天先别读完整章。真正值得抓的是“{focus}”：{teaser}..."


def _why_it_matters(mode: str, keywords: list[str]) -> str:
    focus = "、".join(keywords[:3]) if keywords else "今天这段"
    if mode == "drama":
        return f"叙事内容最容易断在中途。今天先用 {focus} 把前后情绪接上，你会更容易继续看下去。"
    return f"你现在最需要的不是读很多，而是找到一个能进入书的抓手。今天的抓手是：{focus}。"


def _core_question(mode: str, keywords: list[str]) -> str:
    focus = keywords[0] if keywords else "这个观点"
    if mode == "drama":
        return f"这个人物或局势因为“{focus}”发生了什么变化？"
    return f"如果只记住一个问题：{focus} 到底在解决什么真实问题？"


def _plain_explanation(mode: str, paragraphs: list[str], keywords: list[str]) -> str:
    first = paragraphs[0] if paragraphs else ""
    focus = keywords[0] if keywords else "核心内容"
    if mode == "drama":
        return f"白话说，今天这段不是让你记情节流水账，而是看“{focus}”怎样让关系、选择或情绪变得更紧。原文开头的重点是：{first[:180]}"
    return f"白话说，今天这段先把“{focus}”放到你面前。不要急着评价整本书，先看作者如何从这个点切入。原文开头的重点是：{first[:180]}"


def _key_points(paragraphs: list[str], keywords: list[str]) -> list[str]:
    points = []
    for index, keyword in enumerate(keywords[:3], start=1):
        points.append(f"抓手 {index}：留意“{keyword}”在这段里承担的作用。")
    if paragraphs:
        points.append(f"原文入口：第一段已经给出今天的语气和方向，先读懂它。")
    return points or ["今天只需要完成一个动作：读完这一小段，并判断自己是否想继续。"]


def _reality_connection(mode: str, keywords: list[str]) -> str:
    focus = keywords[0] if keywords else "这个内容"
    if mode == "drama":
        return f"把它当成追剧：今天只问“{focus}”让局面多了哪一点不稳定。"
    return f"把它放回现实：如果“{focus}”和你当前的问题无关，今天就只做轻读；如果有关，明天再加深。"


def _after_reading_prompt(mode: str) -> str:
    if mode == "drama":
        return "读完后只回答：你还想知道接下来会怎样吗？"
    return "读完后只回答：这段有没有让你更想继续看这本书？"


def _tomorrow_teaser(mode: str, day_number: int, total_days: int) -> str:
    if day_number >= total_days:
        return "明天可以进入全书复盘：判断这本书是否值得深读、重读或放弃。"
    if mode == "drama":
        return "下一段继续看冲突怎么推进。系统会保持不剧透，只续上你已经读到的位置。"
    return "明天会在今天这个抓手上再推进一点，但仍然只给你一小段。"


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]+", "-", text.strip()).strip("-")
    return slug[:80] or "untitled"


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "source.md"
    safe = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_.-]+", "-", name).strip(".-")
    return safe[:100] or "source.md"


def _source_content_type(suffix: str) -> str:
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".epub":
        return "text/plain"
    return "text/plain"


def _extract_epub_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            rootfile = _epub_rootfile(zf)
            if not rootfile:
                raise GuidedReadingError("invalid EPUB: rootfile missing")
            opf = ElementTree.fromstring(zf.read(rootfile))
            manifest = _epub_manifest(opf)
            spine = _epub_spine(opf)
            base = str(Path(rootfile).parent)
            chunks = []
            for item_id in spine:
                href = manifest.get(item_id)
                if not href:
                    continue
                item_path = str((Path(base) / href).as_posix()) if base != "." else href
                if item_path not in zf.namelist():
                    continue
                if not item_path.lower().endswith((".xhtml", ".html", ".htm")):
                    continue
                html = zf.read(item_path).decode("utf-8", errors="replace")
                text = _html_fragment_to_text(html)
                if text:
                    chunks.append(text)
            if not chunks:
                raise GuidedReadingError("EPUB has no readable XHTML spine content")
            return "\n\n".join(chunks)
    except zipfile.BadZipFile as exc:
        raise GuidedReadingError("invalid EPUB file") from exc
    except ElementTree.ParseError as exc:
        raise GuidedReadingError("invalid EPUB metadata") from exc
    except KeyError as exc:
        raise GuidedReadingError("invalid EPUB: referenced file missing") from exc


def _epub_rootfile(zf: zipfile.ZipFile) -> str:
    try:
        container = ElementTree.fromstring(zf.read("META-INF/container.xml"))
    except KeyError as exc:
        raise GuidedReadingError("invalid EPUB: META-INF/container.xml missing") from exc
    for element in container.iter():
        if _xml_local_name(element.tag) == "rootfile":
            full_path = element.attrib.get("full-path", "").strip()
            if full_path:
                return full_path
    return ""


def _epub_manifest(opf: ElementTree.Element) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for element in opf.iter():
        if _xml_local_name(element.tag) == "item":
            item_id = element.attrib.get("id", "")
            href = element.attrib.get("href", "")
            if item_id and href:
                manifest[item_id] = href
    return manifest


def _epub_spine(opf: ElementTree.Element) -> list[str]:
    ids = []
    for element in opf.iter():
        if _xml_local_name(element.tag) == "itemref":
            item_id = element.attrib.get("idref", "")
            if item_id:
                ids.append(item_id)
    return ids


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _html_fragment_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|section|article|h[1-6]|li|tr)>", "\n", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = unescape(html)
    lines = [" ".join(line.split()) for line in html.splitlines()]
    return "\n\n".join(line for line in lines if line)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
