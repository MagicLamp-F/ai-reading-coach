from __future__ import annotations

import json
import logging
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol

from app.llm import OpenAIChatClient

logger = logging.getLogger(__name__)


class ReflectionAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReflectionAgentResult:
    response: dict[str, Any]
    provider: str
    api_calls: int = 0
    fallback_used: bool = False
    warnings: tuple[str, ...] = ()


class ReflectionAgentAdapter(Protocol):
    name: str

    def generate_reflection(
        self,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
    ) -> ReflectionAgentResult:
        ...


class CustomLLMReflectionAdapter:
    name = "custom"

    def __init__(self, llm: OpenAIChatClient):
        self.llm = llm

    def generate_reflection(
        self,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
    ) -> ReflectionAgentResult:
        response = self.llm.complete_json(system_prompt, user_prompt)
        if not isinstance(response, dict):
            raise ReflectionAdapterError("custom reflection returned no JSON object")
        return ReflectionAgentResult(
            response=response,
            provider=self.name,
            api_calls=1 if getattr(self.llm, "api_key", "") else 0,
        )


class HermesAgentCliAdapter:
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

    def generate_reflection(
        self,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
    ) -> ReflectionAgentResult:
        argv = shlex.split(self.command)
        if not argv:
            raise ReflectionAdapterError("hermes-agent command is empty")

        payload = {
            "task": "ai_reading_coach.reflection",
            "route": "reading.reflection.generate",
            "domain": "reading",
            "memory_scope": ["user_profile", "reading_profile", "book_history"],
            "tool_policy": "none",
            "output_schema": "reflection_v1",
            "format": "json",
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "context": context,
            "output_contract": {
                "period_summary": "string",
                "accurate_observations": ["string"],
                "long_term_interest_changes": ["string"],
                "short_term_focus_changes": ["string"],
                "knowledge_gaps": ["string"],
                "reading_preferences": ["string"],
                "aversion_patterns": ["string"],
                "action_stage": "string",
                "system_misunderstandings": ["string"],
                "next_week_strategy": ["string"],
                "reflection_questions": ["string"],
                "user_md_patch": "markdown string",
                "memory_md_patch": "markdown string",
            },
            "constraints": {
                "do_not_apply_patches": True,
                "human_approval_required": True,
                "do_not_modify_sqlite": True,
                "do_not_send_messages": True,
            },
        }

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
            raise ReflectionAdapterError("hermes-agent command not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise ReflectionAdapterError("hermes-agent timed out") from exc

        if completed.returncode != 0:
            raise ReflectionAdapterError(f"hermes-agent exited with status {completed.returncode}")

        try:
            response = json.loads(completed.stdout or "")
        except json.JSONDecodeError as exc:
            raise ReflectionAdapterError("hermes-agent returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise ReflectionAdapterError("hermes-agent returned non-object JSON")

        return ReflectionAgentResult(response=response, provider=self.name)


class FallbackReflectionAdapter:
    def __init__(self, primary: ReflectionAgentAdapter, fallback: ReflectionAgentAdapter):
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}+fallback:{fallback.name}"

    def generate_reflection(
        self,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
    ) -> ReflectionAgentResult:
        try:
            return self.primary.generate_reflection(system_prompt, user_prompt, context)
        except Exception as exc:
            warning = f"{self.primary.name} failed; fell back to {self.fallback.name}: {exc}"
            logger.warning(warning)
            result = self.fallback.generate_reflection(system_prompt, user_prompt, context)
            return ReflectionAgentResult(
                response=result.response,
                provider=result.provider,
                api_calls=result.api_calls,
                fallback_used=True,
                warnings=(*result.warnings, warning),
            )


def build_reflection_adapter(
    provider: str,
    llm: OpenAIChatClient,
    hermes_agent_command: str,
    hermes_agent_timeout_seconds: float,
) -> ReflectionAgentAdapter:
    custom = CustomLLMReflectionAdapter(llm)
    normalized = provider.strip().lower()
    if normalized in {"", "custom", "custom-llm"}:
        return custom
    if normalized in {"hermes-agent", "hermes_agent", "hermes"}:
        hermes = HermesAgentCliAdapter(
            command=hermes_agent_command,
            timeout_seconds=hermes_agent_timeout_seconds,
        )
        return hermes
    if normalized in {"hermes-agent-fallback", "hermes_agent_fallback", "auto"}:
        hermes = HermesAgentCliAdapter(
            command=hermes_agent_command,
            timeout_seconds=hermes_agent_timeout_seconds,
        )
        return FallbackReflectionAdapter(hermes, custom)
    raise ValueError(f"Unsupported HERMES_REFLECTION_PROVIDER: {provider}")
