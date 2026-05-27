import tempfile
import unittest
from pathlib import Path

from app.memory import TRUNCATION_MARKER, load_long_term_memory_context


class MemoryLoaderTests(unittest.TestCase):
    def test_missing_memory_files_degrade_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = load_long_term_memory_context(Path(tmp) / "missing")

        self.assertIn("暂无 Hermes long-term memory", context)

    def test_overlong_memory_is_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "USER.md").write_text("A" * 200, encoding="utf-8")
            (memory_dir / "MEMORY.md").write_text("B" * 200, encoding="utf-8")

            context = load_long_term_memory_context(memory_dir, max_chars=80)

        self.assertLessEqual(len(context), 80)
        self.assertIn(TRUNCATION_MARKER, context)


if __name__ == "__main__":
    unittest.main()
