import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from app.db import connect, init_db
from app.guided_reading import GuidedReadingService
from app.repository import Repository


class GuidedReadingServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.source_path = Path(self.tmp.name) / "source.md"
        self.source_path.write_text(
            "\n\n".join(
                [
                    "第一段讲效率和优先级。真正的问题不是时间不够，而是判断标准不清楚。",
                    "第二段继续说明反馈闭环。系统需要每天根据行为调整，而不是一次性制定完美计划。",
                    "第三段把问题放回现实。用户没有耐心时，入口必须足够短，反馈必须足够轻。",
                    "第四段说明明天应该继续推进，但不要突然加大难度。",
                ]
            ),
            encoding="utf-8",
        )
        self.conn = connect(self.db_path)
        init_db(self.conn)
        self.repo = Repository(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_create_plan_splits_source_and_generates_daily_packs(self):
        result = GuidedReadingService(self.repo, library_dir=Path(self.tmp.name) / "library").create_plan_from_source(
            source_path=self.source_path,
            title="低耐心阅读",
            author="A",
            plan_days=2,
            daily_minutes=8,
            start_date=date(2026, 6, 3),
            lark_push_enabled=True,
        )

        self.assertEqual(len(result.day_ids), 2)
        days = self.repo.reading_plan_days(result.plan_id)
        self.assertEqual([int(day["day_number"]) for day in days], [1, 2])
        self.assertEqual(days[0]["scheduled_date"], "2026-06-03")

        page = self.repo.get_guided_reading_day_page(result.first_day_id)
        self.assertIsNotNone(page)
        self.assertEqual(page["book_title"], "低耐心阅读")
        self.assertEqual(int(page["lark_push_enabled"]), 1)
        self.assertIn('"hook"', page["content_json"])
        self.assertIn("第一段讲效率", page["source_text"])

        due = self.repo.next_lark_push_reading_days()
        self.assertGreaterEqual(len(due), 1)
        self.assertEqual(int(due[0]["id"]), result.first_day_id)

    def test_import_source_file_and_create_plan_from_source_file(self):
        source_id = GuidedReadingService(self.repo, library_dir=Path(self.tmp.name) / "library").import_source_file(
            source_path=self.source_path,
            title="导入书源",
            author="A",
            original_filename="source.md",
        )

        row = self.repo.get_reading_source_file(source_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "导入书源")
        self.assertEqual(row["file_format"], "md")
        self.assertGreater(int(row["char_count"]), 120)

        result = GuidedReadingService(self.repo, library_dir=Path(self.tmp.name) / "library").create_plan_from_source_file(
            source_file_id=source_id,
            plan_days=2,
            daily_minutes=8,
        )
        self.assertEqual(len(result.day_ids), 2)

    def test_import_epub_extracts_spine_text(self):
        epub_path = Path(self.tmp.name) / "book.epub"
        self._write_minimal_epub(epub_path)

        source_id = GuidedReadingService(self.repo, library_dir=Path(self.tmp.name) / "library").import_source_file(
            source_path=epub_path,
            title="EPUB 书源",
            author="A",
            original_filename="book.epub",
        )

        row = self.repo.get_reading_source_file(source_id)
        self.assertEqual(row["file_format"], "epub")
        stored = Path(row["stored_path"]).read_text(encoding="utf-8")
        self.assertIn("第一章说明 EPUB 导入", stored)
        self.assertIn("第二章继续说明 spine 顺序", stored)

        result = GuidedReadingService(self.repo, library_dir=Path(self.tmp.name) / "library").create_plan_from_source_file(
            source_file_id=source_id,
            plan_days=2,
            daily_minutes=8,
        )
        self.assertEqual(len(result.day_ids), 2)

    def _write_minimal_epub(self, path: Path) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr(
                "META-INF/container.xml",
                """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""",
            )
            zf.writestr(
                "OPS/content.opf",
                """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <manifest>
    <item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
    <itemref idref="c2"/>
  </spine>
</package>""",
            )
            zf.writestr(
                "OPS/chapter1.xhtml",
                """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>第一章</h1>
<p>第一章说明 EPUB 导入需要按 spine 顺序读取 XHTML 正文，而且要去掉标签。</p>
<p>这一段补充足够长度，确保导入校验能够通过，并让后续阅读计划可以切分。</p>
</body></html>""",
            )
            zf.writestr(
                "OPS/chapter2.xhtml",
                """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>第二章</h1>
<p>第二章继续说明 spine 顺序很重要，因为目录顺序和 zip 文件顺序不一定一致。</p>
<p>这一段继续补充文本，让 EPUB 导入后的内容能够生成每日导读包。</p>
</body></html>""",
            )


if __name__ == "__main__":
    unittest.main()
