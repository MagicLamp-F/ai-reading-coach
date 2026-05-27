from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LONG_TERM_MEMORY_MAX_CHARS = 6000
MEMORY_FILES = ("USER.md", "MEMORY.md")
TRUNCATION_MARKER = "\n...[truncated]"
EMPTY_LONG_TERM_MEMORY_CONTEXT = "暂无 Hermes long-term memory。"


def load_long_term_memory_context(
    memory_dir: Path = Path("memory"),
    max_chars: int = DEFAULT_LONG_TERM_MEMORY_MAX_CHARS,
) -> str:
    sections = []
    for filename in MEMORY_FILES:
        content = _read_memory_file(memory_dir / filename, max_chars + 1)
        if content:
            sections.append(f"{filename}:\n{content}")

    if not sections:
        return EMPTY_LONG_TERM_MEMORY_CONTEXT

    return _truncate("\n\n".join(sections), max_chars)


def _read_memory_file(path: Path, read_limit: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return handle.read(read_limit).strip()
    except OSError as exc:
        logger.warning("Hermes memory file read failed: path=%s error=%s", path, exc)
        return ""


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    marker = TRUNCATION_MARKER
    if max_chars <= len(marker):
        return text[:max_chars]
    return text[: max_chars - len(marker)].rstrip() + marker
