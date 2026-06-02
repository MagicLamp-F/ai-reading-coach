import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.db import connect, init_db
from app.http_client import TextHttpResponse
from app.repository import RecommendationDraft, Repository
from app.search import SearchResult
from app.source_collector import (
    BookSourceCollector,
    is_article_like_book_source_url,
    is_preferred_book_landing_url,
    is_safe_book_source_url,
    parse_html_source,
    source_quality_from_sources,
)


class FakeHttp:
    def __init__(self, body: str, status: int = 200):
        self.body = body
        self.status = status
        self.urls = []

    def get_text(self, url, headers=None, max_bytes=200_000):
        self.urls.append(url)
        return TextHttpResponse(
            status=self.status,
            body=self.body,
            final_url=url,
            content_type="text/html; charset=utf-8",
        )


class FakeSearch:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def search_books(self, query, max_results=5, search_depth="basic", include_raw_content=False):
        self.queries.append((query, max_results, search_depth, include_raw_content))
        return self.results[:max_results]


class SourceCollectorTests(unittest.TestCase):
    def test_parse_html_source_removes_scripts_and_normalizes_text(self):
        parsed = parse_html_source(
            """
            <html><head><title>Book Page</title><script>secret()</script></head>
            <body><h1>Book Page</h1><p>First paragraph.</p><style>.x{}</style><p>Second paragraph.</p></body></html>
            """
        )

        self.assertEqual(parsed.title, "Book Page")
        self.assertIn("First paragraph.", parsed.text)
        self.assertIn("Second paragraph.", parsed.text)
        self.assertNotIn("secret", parsed.text)

    def test_collect_for_recommendation_persists_public_source_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _repo_with_recommendation(Path(tmp), "https://example.com/book")
            recommendation = repo.get_recommendation_detail(1)
            http = FakeHttp("<html><title>Official Book</title><body><p>Public source excerpt about the book.</p></body></html>")
            collector = BookSourceCollector(repo, http, max_excerpt_chars=80)

            collected = collector.collect_for_recommendation(recommendation)
            stored = repo.book_sources_for_book(1)

            self.assertEqual(len(collected), 1)
            self.assertEqual(stored[0]["title"], "Official Book")
            self.assertIn("Public source excerpt", stored[0]["text_excerpt"])

    def test_collect_for_recommendation_fetches_tavily_search_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _repo_with_recommendation(Path(tmp), "")
            recommendation = repo.get_recommendation_detail(1)
            http = FakeHttp("<html><title>Book Review</title><body><p>This book review explains key examples.</p></body></html>")
            search = FakeSearch([SearchResult(title="Book Review", url="https://example.com/review", content="review snippet")])
            collector = BookSourceCollector(repo, http, search=search, max_search_results=2)

            collected = collector.collect_for_recommendation(recommendation)
            stored = repo.book_sources_for_book(1)

            self.assertEqual(len(collected), 1)
            self.assertEqual(search.queries[0][1], 2)
            self.assertEqual(stored[0]["source_type"], "review")
            self.assertIn("Book Review", stored[0]["title"])

    def test_collect_for_recommendation_uses_tavily_raw_content_before_fetching_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _repo_with_recommendation(Path(tmp), "")
            recommendation = repo.get_recommendation_detail(1)
            http = FakeHttp("<html><title>Should Not Fetch</title><body><p>unused</p></body></html>")
            search = FakeSearch(
                [
                    SearchResult(
                        title="Sample Chapter",
                        url="https://example.com/sample",
                        content="sample snippet",
                        raw_content="Sample chapter text with concrete examples.",
                    )
                ]
            )
            collector = BookSourceCollector(repo, http, search=search, max_search_results=1)

            collected = collector.collect_for_recommendation(recommendation)
            stored = repo.book_sources_for_book(1)

            self.assertEqual(len(collected), 1)
            self.assertEqual(http.urls, [])
            self.assertTrue(search.queries[0][3])
            self.assertEqual(stored[0]["source_type"], "sample_chapter")
            self.assertIn("Sample chapter text", stored[0]["text_excerpt"])

    def test_source_quality_scores_visible_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _repo_with_recommendation(Path(tmp), "https://example.com/book")
            recommendation = repo.get_recommendation_detail(1)
            http = FakeHttp("<html><title>Official Book</title><body><p>Official page.</p></body></html>")
            collector = BookSourceCollector(repo, http)

            collector.collect_for_recommendation(recommendation)
            quality = source_quality_from_sources(repo.book_sources_for_book(1))

            self.assertEqual(quality["status"], "source_limited")
            self.assertEqual(quality["source_count"], 1)
            self.assertIn("official_page", quality["source_types"])

    def test_is_safe_book_source_url_blocks_suspicious_pdf_sources(self):
        self.assertFalse(is_safe_book_source_url("https://dokumen.pub/some-book.pdf", "Some Book PDF"))
        self.assertFalse(is_safe_book_source_url("https://example.com/book.pdf", "[PDF] Full Book"))
        self.assertFalse(is_safe_book_source_url("https://reachone01.github.io/novel/foundation/index.html", "银河帝国1to15 在线阅读"))
        self.assertTrue(is_safe_book_source_url("https://www.thoughtworks.com/sample.pdf", "Sample Chapter PDF"))

    def test_book_landing_url_classification_prefers_books_over_articles(self):
        self.assertTrue(is_article_like_book_source_url("https://developer.aliyun.com/article/1647908"))
        self.assertTrue(is_article_like_book_source_url("https://www.cnblogs.com/example/p/123.html"))
        self.assertTrue(is_preferred_book_landing_url("https://www.oreilly.com/library/view/building-evolutionary-architectures/9781491986356/", "[Book]"))
        self.assertTrue(is_preferred_book_landing_url("https://www.thoughtworks.com/content/dam/thoughtworks/documents/books/sample.pdf", "Sample Chapter"))
        self.assertFalse(is_preferred_book_landing_url("https://developer.aliyun.com/article/1647908", "云厂商文章"))

    def test_collect_for_recommendation_skips_local_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _repo_with_recommendation(Path(tmp), "http://127.0.0.1:8000/admin")
            recommendation = repo.get_recommendation_detail(1)
            http = FakeHttp("<html></html>")
            collector = BookSourceCollector(repo, http)

            collected = collector.collect_for_recommendation(recommendation)

            self.assertEqual(collected, [])
            self.assertEqual(http.urls, [])


def _repo_with_recommendation(tmp_path: Path, source_url: str) -> Repository:
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    repo = Repository(conn)
    run_id = repo.create_run("test")
    repo.add_recommendation(
        run_id,
        RecommendationDraft(
            title="测试书",
            author="作者",
            source_url=source_url,
            slot_type="profile_fit",
            theme="工程化复盘",
            recommendation_reason="推荐理由",
            profile_mapping="画像映射",
            system_hypothesis="系统假设",
            profile_dimensions=["reading_preference"],
            expected_benefit="收益",
            risk="风险",
            reading_suggestion="读法",
            metadata={"source": "test"},
        ),
        date(2026, 5, 31),
    )
    return repo


if __name__ == "__main__":
    unittest.main()
