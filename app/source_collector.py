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
from app.search import SearchResult

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_EXCERPT_CHARS = 9000


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
        search=None,
        max_excerpt_chars: int = DEFAULT_SOURCE_EXCERPT_CHARS,
        search_enabled: bool = True,
        max_search_results: int = 5,
        search_depth: str = "advanced",
        search_queries_per_book: int = 6,
        include_raw_content: bool = True,
    ):
        self.repo = repo
        self.http = http
        self.search = search
        self.max_excerpt_chars = max_excerpt_chars
        self.search_enabled = search_enabled
        self.max_search_results = max_search_results
        self.search_depth = search_depth
        self.search_queries_per_book = search_queries_per_book
        self.include_raw_content = include_raw_content

    def collect_for_recommendation(self, recommendation) -> list[CollectedBookSource]:
        return self.collect_for_book(
            book_id=int(recommendation["book_id"]),
            title=str(recommendation["title"] or ""),
            author=str(recommendation["author"] or ""),
            source_url=str(recommendation["source_url"] or ""),
        )

    def collect_for_book(self, book_id: int, title: str, author: str = "", source_url: str = "") -> list[CollectedBookSource]:
        url = source_url.strip()
        collected: list[CollectedBookSource] = []
        if url and is_safe_book_source_url(url):
            source = self._collect_url(book_id, url, "official_page", {"collector_provider": "recommendation_source_url"})
            if source is not None:
                collected.append(source)
        collected.extend(self._collect_search_results(book_id, title, author))
        return collected

    def _collect_url(
        self,
        book_id: int,
        url: str,
        source_type: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> CollectedBookSource | None:
        try:
            response = self.http.get_text(url, max_bytes=200_000)
            if response.status >= 400:
                logger.warning("Book source fetch returned HTTP %s for book_id=%s", response.status, book_id)
                return None
            parsed = parse_html_source(response.body)
            excerpt = parsed.text[: self.max_excerpt_chars]
            if not excerpt.strip():
                return None
            inferred_source_type = _classify_source(source_type, parsed.title, response.final_url or url, excerpt)
            metadata = {
                "status": response.status,
                "final_url": response.final_url,
                "content_type": response.content_type,
                "excerpt_chars": len(excerpt),
                "collector": "http_source_collector_v2",
                **(extra_metadata or {}),
            }
            source_id = self.repo.upsert_book_source(
                BookSourceDraft(
                    book_id=book_id,
                    source_type=inferred_source_type,
                    url=response.final_url or url,
                    title=parsed.title[:300],
                    text_excerpt=excerpt,
                    metadata=metadata,
                )
            )
            return CollectedBookSource(
                id=source_id,
                source_type=inferred_source_type,
                url=response.final_url or url,
                title=parsed.title[:300],
                text_excerpt=excerpt,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("Book source collection failed for book_id=%s: %s", book_id, exc)
            return None

    def _collect_search_results(self, book_id: int, title: str, author: str = "") -> list[CollectedBookSource]:
        if not self.search_enabled or self.search is None:
            return []
        title = title.strip()
        author = author.strip()
        if not title:
            return []
        collected = []
        seen_urls = set()
        for query in _source_search_queries(title, author)[: max(1, self.search_queries_per_book)]:
            try:
                results = self.search.search_books(
                    query,
                    max_results=self.max_search_results,
                    search_depth=self.search_depth,
                    include_raw_content=self.include_raw_content,
                )
            except TypeError:
                results = self.search.search_books(query, max_results=self.max_search_results)
            except Exception as exc:
                logger.warning("Book source search failed for title=%s query=%s: %s", title, query, exc)
                continue
            for result in results:
                url = _source_value(result, "url").strip()
                result_title = _source_value(result, "title").strip()
                content = _source_value(result, "content")
                raw_content = _source_value(result, "raw_content")
                if not url or url in seen_urls or not is_safe_book_source_url(url, result_title):
                    continue
                seen_urls.add(url)
                metadata = {
                    "collector_provider": "tavily",
                    "search_depth": self.search_depth,
                    "include_raw_content": self.include_raw_content,
                    "search_query": query,
                    "search_result_title": result_title,
                    "search_result_snippet": content[:500],
                }
                raw_text = raw_content.strip()
                if raw_text:
                    source = self._store_text_source(
                        book_id,
                        url,
                        result_title,
                        raw_text,
                        "search_result",
                        metadata,
                    )
                else:
                    source = self._collect_url(
                        book_id,
                        url,
                        "search_result",
                        metadata,
                    )
                if source is not None:
                    collected.append(source)
        return collected

    def _store_text_source(
        self,
        book_id: int,
        url: str,
        title: str,
        text: str,
        source_type: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> CollectedBookSource | None:
        excerpt = _normalize_text(text)[: self.max_excerpt_chars]
        if not excerpt.strip():
            return None
        inferred_source_type = _classify_source(source_type, title, url, excerpt)
        metadata = {
            "excerpt_chars": len(excerpt),
            "collector": "tavily_raw_content_v1",
            **(extra_metadata or {}),
        }
        source_id = self.repo.upsert_book_source(
            BookSourceDraft(
                book_id=book_id,
                source_type=inferred_source_type,
                url=url,
                title=title[:300],
                text_excerpt=excerpt,
                metadata=metadata,
            )
        )
        return CollectedBookSource(
            id=source_id,
            source_type=inferred_source_type,
            url=url,
            title=title[:300],
            text_excerpt=excerpt,
            metadata=metadata,
        )


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


def is_safe_book_source_url(url: str, title: str = "") -> bool:
    if not _is_fetchable_public_url(url):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    blocked_hosts = {
        "dokumen.pub",
        "pdfcoffee.com",
        "vdoc.pub",
        "epdf.pub",
        "pdfdrive.com",
        "www.pdfdrive.com",
        "z-lib.org",
        "libgen.is",
        "libgen.rs",
        "annas-archive.org",
        "oceanofpdf.com",
        "reachone01.github.io",
    }
    if host in blocked_hosts or any(host.endswith(f".{blocked}") for blocked in blocked_hosts):
        return False
    piracy_hints = ["full text", "全文", "在线阅读", "novel/", "/novel/", "小说"]
    if any(token in f"{host} {path} {title.lower()}" for token in piracy_hints):
        trusted_reading_domains = ("readmoo.com", "goodreads.com", "openlibrary.org", "books.google.com")
        if not any(host == domain or host.endswith(f".{domain}") for domain in trusted_reading_domains):
            return False
    looks_like_pdf = path.endswith(".pdf") or "[pdf]" in title.lower()
    if looks_like_pdf:
        lower_title = title.lower()
        safe_pdf_domains = ("thoughtworks.com", "sei.cmu.edu", "cmu.edu", "oreilly.com")
        if "sample" in lower_title or "sample chapter" in lower_title:
            return True
        if any(host == domain or host.endswith(f".{domain}") for domain in safe_pdf_domains):
            return True
        return False
    return True


def is_preferred_book_landing_url(url: str, title: str = "") -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    haystack = f"{host} {path} {title}".lower()
    preferred_domains = {
        "oreilly.com",
        "thoughtworks.com",
        "tup.com.cn",
        "douban.com",
        "m.douban.com",
        "readmoo.com",
        "goodreads.com",
        "amazon.com",
        "books.google.com",
        "worldcat.org",
        "openlibrary.org",
        "penguinrandomhouse.com",
        "mitpress.mit.edu",
        "nostarch.com",
        "mannings.com",
        "manning.com",
        "pragprog.com",
        "informit.com",
        "pearson.com",
        "springer.com",
    }
    if any(host == domain or host.endswith(f".{domain}") for domain in preferred_domains):
        return True
    return any(
        token in haystack
        for token in [
            "/book",
            "/books",
            "/library/view",
            "book_",
            "subject/",
            "isbn",
            "sample chapter",
            "[book]",
            "图书",
            "出版社",
        ]
    )


def is_article_like_book_source_url(url: str, title: str = "") -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    haystack = f"{host} {path} {title}".lower()
    article_domains = {
        "developer.aliyun.com",
        "cloud.tencent.com",
        "huaweicloud.com",
        "aws.amazon.com",
        "azure.microsoft.com",
        "cnblogs.com",
        "juejin.cn",
        "jianshu.com",
        "medium.com",
        "dev.to",
    }
    if any(host == domain or host.endswith(f".{domain}") for domain in article_domains):
        return True
    return any(token in haystack for token in ["/article/", "/blog/", "/posts/", "/p/"])


def _classify_source(default_type: str, title: str, url: str, text: str) -> str:
    haystack = f"{title} {url} {text[:1500]}".lower()
    if any(token in haystack for token in ["table of contents", "contents", "目录"]):
        return "table_of_contents"
    if any(token in haystack for token in ["sample chapter", "excerpt", "read an excerpt", "样章", "试读"]):
        return "sample_chapter"
    if any(token in haystack for token in ["interview", "podcast", "conversation", "访谈", "采访"]):
        return "author_interview"
    if any(token in haystack for token in ["review", "book notes", "summary", "书评", "读书笔记"]):
        return "review"
    if default_type == "search_result":
        return "public_page"
    return default_type


def source_quality_from_sources(sources: list[Any]) -> dict[str, Any]:
    types = {_source_value(source, "source_type") for source in sources}
    total_excerpt_chars = sum(len(_source_value(source, "text_excerpt")) for source in sources)
    score = 0.0
    if types:
        score += 0.10
    score += min(max(len(sources) - 1, 0) * 0.06, 0.18)
    score += min(total_excerpt_chars / 20_000 * 0.15, 0.15)
    if types.intersection({"official_page", "public_page"}):
        score += 0.15
    if "table_of_contents" in types:
        score += 0.25
    if "sample_chapter" in types:
        score += 0.25
    if "author_interview" in types:
        score += 0.15
    if "review" in types:
        score += 0.10
    score = min(score, 1.0)
    if score >= 0.70:
        status = "source_rich"
    elif score >= 0.50:
        status = "source_usable"
    elif score > 0:
        status = "source_limited"
    else:
        status = "source_missing"
    return {
        "status": status,
        "score": round(score, 2),
        "source_count": len(sources),
        "clean_text_chars": total_excerpt_chars,
        "source_types": sorted(source_type for source_type in types if source_type),
    }


def _source_value(source: Any, key: str) -> str:
    try:
        value = source[key]
    except (KeyError, TypeError, IndexError):
        value = getattr(source, key, "")
    if value is None:
        return ""
    return str(value)


def _source_search_queries(title: str, author: str) -> list[str]:
    base = f'"{title}" "{author}"'.strip()
    return [
        f"{base} book table of contents chapter outline sample chapter",
        f"{base} publisher official book page isbn overview",
        f"{base} excerpt sample chapter preview read an excerpt",
        f"{base} author interview lecture podcast transcript key ideas",
        f"{base} book review summary notes examples criticism",
        f"{base} course syllabus reading guide discussion questions",
    ]
