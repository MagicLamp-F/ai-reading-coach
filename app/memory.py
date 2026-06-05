from __future__ import annotations

import logging
import json
import shlex
import subprocess
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

DEFAULT_LONG_TERM_MEMORY_MAX_CHARS = 6000
DEFAULT_HERMES_NATIVE_PROFILE_MAX_CHARS = 6000
MEMORY_FILES = ("USER.md", "MEMORY.md")
TRUNCATION_MARKER = "\n...[truncated]"
EMPTY_LONG_TERM_MEMORY_CONTEXT = "暂无 Hermes long-term memory。"
EMPTY_HERMES_NATIVE_PROFILE_CONTEXT = "暂无 Hermes native profile snapshot。"
DEFAULT_HERMES_NATIVE_PROFILE_PATH = Path("memory/HERMES_NATIVE_PROFILE.md")
DEFAULT_HERMES_SOUL_PATH = Path("/home/ubuntu/.hermes/SOUL.md")
_NATIVE_PROFILE_LOAD_COUNTS = {"snapshot": 0, "generated_snapshot": 0, "soul_fallback": 0, "missing": 0}
_NATIVE_PROFILE_LOAD_COUNTS_LOCK = Lock()
INSUFFICIENT_PROFILE_MARKERS = (
    "Not enough personal reading facts",
    "does not contain enough personal reading facts",
    "没有足够个人阅读事实",
    "缺少个人阅读事实",
)


class HermesNativeProfileProvider:
    def __init__(
        self,
        snapshot_path: Path = DEFAULT_HERMES_NATIVE_PROFILE_PATH,
        fallback_soul_path: Path = DEFAULT_HERMES_SOUL_PATH,
        max_chars: int = DEFAULT_HERMES_NATIVE_PROFILE_MAX_CHARS,
        generator_command: str = "",
        generator_timeout_seconds: float = 60.0,
        runner=subprocess.run,
    ):
        self.snapshot_path = snapshot_path
        self.fallback_soul_path = fallback_soul_path
        self.max_chars = max_chars
        self.generator_command = generator_command.strip()
        self.generator_timeout_seconds = generator_timeout_seconds
        self.runner = runner

    def load_context(self, seed_context: str = "") -> str:
        snapshot = _read_memory_file(self.snapshot_path, self.max_chars + 1)
        if snapshot:
            if self.generator_command and seed_context.strip() and _is_insufficient_native_profile(snapshot):
                generated = self._generate_snapshot(
                    _read_memory_file(self.fallback_soul_path, self.max_chars + 1),
                    seed_context,
                )
                self.snapshot_path.write_text(generated.rstrip() + "\n", encoding="utf-8")
                _record_native_profile_load("generated_snapshot")
                logger.info("Hermes native profile snapshot refreshed from ARC evidence: snapshot_path=%s", self.snapshot_path)
                return _truncate(f"{self.snapshot_path.name}:\n{generated}", self.max_chars)
            _record_native_profile_load("snapshot")
            return _truncate(f"{self.snapshot_path.name}:\n{snapshot}", self.max_chars)

        soul = _read_memory_file(self.fallback_soul_path, self.max_chars + 1)
        if soul:
            if self.generator_command:
                generated = self._generate_snapshot(soul, seed_context)
                self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                self.snapshot_path.write_text(generated.rstrip() + "\n", encoding="utf-8")
                _record_native_profile_load("generated_snapshot")
                logger.info(
                    "Hermes native profile snapshot generated: snapshot_path=%s fallback_path=%s",
                    self.snapshot_path,
                    self.fallback_soul_path,
                )
                return _truncate(f"{self.snapshot_path.name}:\n{generated}", self.max_chars)
            _record_native_profile_load("soul_fallback")
            logger.info(
                "Hermes native profile snapshot missing; using SOUL fallback: snapshot_path=%s fallback_path=%s",
                self.snapshot_path,
                self.fallback_soul_path,
            )
            return _truncate(f"{self.fallback_soul_path.name} fallback:\n{soul}", self.max_chars)

        _record_native_profile_load("missing")
        return EMPTY_HERMES_NATIVE_PROFILE_CONTEXT

    def _generate_snapshot(self, soul: str, seed_context: str = "") -> str:
        argv = shlex.split(self.generator_command)
        if not argv:
            raise RuntimeError("Hermes native profile generator command is empty")
        payload = {
            "route": "reading.profile.sync_snapshot",
            "output_schema": "profile_snapshot_v1",
            "system_prompt": "Return exactly one JSON object with one key: markdown.",
            "user_prompt": (
                "Create a concise HERMES_NATIVE_PROFILE.md snapshot for ai-reading-coach. "
                "Use ARC evidence as the primary user-reading evidence. Use SOUL only as low-priority background, "
                "because SOUL may describe the assistant rather than the user. "
                "Separate stable facts from hypotheses; cite source types in Source Notes. "
                "If evidence is weak, keep it under Open Questions instead of inventing preferences. "
                "Output exactly this JSON shape and no other text: "
                '{"markdown":"# HERMES_NATIVE_PROFILE\\n\\n## Stable Identity\\n...\\n\\n## Long-term Interests\\n...\\n\\n'
                '## Reading Preferences\\n...\\n\\n## Thinking Style\\n...\\n\\n## Current Stage\\n...\\n\\n'
                '## Aversion Patterns\\n...\\n\\n## Open Questions\\n...\\n\\n## Source Notes\\n..."}'
            ),
            "context": {"soul": soul[: self.max_chars], "arc_evidence": seed_context[: self.max_chars]},
            "output_contract": {"markdown": "markdown string"},
            "constraints": {
                "do_not_modify_sqlite": True,
                "do_not_send_messages": True,
                "do_not_apply_patches": True,
                "business_orchestrator_writes_snapshot": True,
            },
        }
        try:
            completed = self.runner(
                argv,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.generator_timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Hermes native profile generator command not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Hermes native profile generator timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip() or (completed.stdout or "").strip()
            raise RuntimeError(f"Hermes native profile generator failed: {detail[:500]}")
        try:
            response = json.loads(completed.stdout or "")
        except json.JSONDecodeError as exc:
            raise RuntimeError("Hermes native profile generator returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise RuntimeError("Hermes native profile generator returned non-object JSON")
        markdown = str(response.get("markdown") or "").strip()
        if not markdown:
            raise RuntimeError("Hermes native profile generator returned empty markdown")
        if not markdown.startswith("# HERMES_NATIVE_PROFILE"):
            markdown = "# HERMES_NATIVE_PROFILE\n\n" + markdown
        return markdown


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


def build_daily_profile_context(
    structured_profile_context: str,
    long_term_memory_context: str,
    hermes_native_profile_context: str = EMPTY_HERMES_NATIVE_PROFILE_CONTEXT,
) -> str:
    return (
        "Priority 1: Hermes native profile snapshot:\n"
        f"{hermes_native_profile_context.strip() or EMPTY_HERMES_NATIVE_PROFILE_CONTEXT}\n\n"
        "Priority 2: User explicit ARC feedback:\n"
        "已处理的明确反馈会作为 evidence 进入 ARC structured reading profile；"
        "自由文本和明确自述优先于 ARC 推断。\n\n"
        "Priority 3: ARC inferred reading profile:\n"
        f"{structured_profile_context.strip() or '暂无画像。'}\n\n"
        "Priority 4: ARC applied reflection memory:\n"
        f"{long_term_memory_context.strip() or EMPTY_LONG_TERM_MEMORY_CONTEXT}\n\n"
        "Priority 5: Single-run weak signals:\n"
        "仅把本次搜索结果、候选书源和单次弱反馈作为待验证假设，不要写成长期偏好。"
    )


def build_native_profile_seed_context(structured_profile_context: str, long_term_memory_context: str) -> str:
    return (
        "ARC structured reading profile evidence:\n"
        f"{structured_profile_context.strip() or '暂无 ARC reading profile evidence。'}\n\n"
        "ARC applied reflection memory evidence:\n"
        f"{long_term_memory_context.strip() or '暂无 ARC applied reflection memory evidence。'}"
    )


def hermes_native_profile_load_metrics() -> dict[str, int]:
    with _NATIVE_PROFILE_LOAD_COUNTS_LOCK:
        return dict(_NATIVE_PROFILE_LOAD_COUNTS)


def _read_memory_file(path: Path, read_limit: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return handle.read(read_limit).strip()
    except OSError as exc:
        logger.warning("Hermes memory file read failed: path=%s error=%s", path, exc)
        return ""


def _record_native_profile_load(source: str) -> None:
    with _NATIVE_PROFILE_LOAD_COUNTS_LOCK:
        _NATIVE_PROFILE_LOAD_COUNTS[source] = _NATIVE_PROFILE_LOAD_COUNTS.get(source, 0) + 1


def _is_insufficient_native_profile(text: str) -> bool:
    return any(marker in text for marker in INSUFFICIENT_PROFILE_MARKERS)


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    marker = TRUNCATION_MARKER
    if max_chars <= len(marker):
        return text[:max_chars]
    return text[: max_chars - len(marker)].rstrip() + marker
