from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from app.http_client import HttpClient
from app.repository import BookSourceDraft, Repository

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_EXCERPT_CHARS = 6000


@dataclass(frozen=True)
class CollectedBookSource:
    id: int
    source_type: str
    url: str
    title: str
    text_excerpt: str
    metadata: dict[str, Any]


class BookSourceCollector:
    def __init__(
        self,
        repo: Repository,
        http: HttpClient,
        max_excerpt_chars: int = DEFAULT_SOURCE_EXCERPT_CHARS,
    ):
        self.repo = repo
        self.http = http
        self.max_excerpt_chars = max_excerpt_chars

    def collect_for_recommendation(self, recommendation) -> list[CollectedBookSource]:
        url = str(recommendation["source_url"] or "").strip()
        book_id = int(recommendation["book_id"])
        if not url or not _is_fetchable_public_url(url):
            return []
        try:
            response = self.http.get_text(url, max_bytes=200_000)
            if response.status >= 400:
                logger.warning("Book source fetch returned HTTP %s for book_id=%s", response.status, book_id)
                return []
            parsed = parse_html_source(response.body)
            excerpt = parsed.text[: self.max_excerpt_chars]
            if not excerpt.strip():
                return []
            metadata = {
                "status": response.status,
                "final_url": response.final_url,
                "content_type": response.content_type,
                "excerpt_chars": len(excerpt),
                "collector": "http_source_collector_v1",
            }
            source_id = self.repo.upsert_book_source(
                BookSourceDraft(
                    book_id=book_id,
                    source_type="official_page",
                    url=response.final_url or url,
                    title=parsed.title[:300],
                    text_excerpt=excerpt,
                    metadata=metadata,
                )
            )
            return [
                CollectedBookSource(
                    id=source_id,
                    source_type="official_page",
                    url=response.final_url or url,
                    title=parsed.title[:300],
                    text_excerpt=excerpt,
                    metadata=metadata,
                )
            ]
        except Exception as exc:
            logger.warning("Book source collection failed for book_id=%s: %s", book_id, exc)
            return []


@dataclass(frozen=True)
class ParsedHtmlSource:
    title: str
    text: str


class _ReadableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        self.text_parts.append(text)


def parse_html_source(html: str) -> ParsedHtmlSource:
    parser = _ReadableHTMLParser()
    parser.feed(html)
    title = _normalize_text(" ".join(parser.title_parts))
    text = _normalize_text("\n".join(parser.text_parts))
    return ParsedHtmlSource(title=title, text=text)


def _normalize_text(value: str) -> str:
    lines = []
    for line in value.replace("\r", "\n").split("\n"):
        normalized = re.sub(r"\s+", " ", line).strip()
        if normalized:
            lines.append(normalized)
    return "\n".join(lines)


def _is_fetchable_public_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname
    if not host:
        return False
    normalized_host = host.lower()
    if normalized_host in {"localhost", "localhost.localdomain"} or normalized_host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(normalized_host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)
