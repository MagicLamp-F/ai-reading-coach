import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.db import connect, init_db
from app.http_client import TextHttpResponse
from app.repository import RecommendationDraft, Repository
from app.source_collector import BookSourceCollector, parse_html_source


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
