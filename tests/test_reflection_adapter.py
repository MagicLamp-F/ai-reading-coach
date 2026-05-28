import json
import subprocess
import unittest

from app.reflection_adapter import (
    CustomLLMReflectionAdapter,
    FallbackReflectionAdapter,
    HermesAgentCliAdapter,
    ReflectionAdapterError,
)


class FakeLLM:
    api_key = "test-key"

    def __init__(self, response=None):
        self.response = response or {"period_summary": "custom"}
        self.calls = []

    def complete_json(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        return self.response


class FailingAdapter:
    name = "failing"

    def generate_reflection(self, system_prompt, user_prompt, context):
        raise ReflectionAdapterError("boom")


class StaticAdapter:
    name = "static"

    def generate_reflection(self, system_prompt, user_prompt, context):
        from app.reflection_adapter import ReflectionAgentResult

        return ReflectionAgentResult(
            response={"period_summary": "fallback"},
            provider=self.name,
            api_calls=1,
        )


class ReflectionAdapterTests(unittest.TestCase):
    def test_custom_adapter_calls_existing_llm(self):
        llm = FakeLLM({"period_summary": "ok"})
        adapter = CustomLLMReflectionAdapter(llm)

        result = adapter.generate_reflection("system", "user", {"days": 7})

        self.assertEqual(result.provider, "custom")
        self.assertEqual(result.api_calls, 1)
        self.assertEqual(result.response["period_summary"], "ok")
        self.assertEqual(llm.calls, [("system", "user")])

    def test_hermes_agent_cli_sends_contract_and_parses_json(self):
        calls = []

        def runner(argv, input, text, capture_output, timeout, check):
            calls.append(
                {
                    "argv": argv,
                    "payload": json.loads(input),
                    "text": text,
                    "capture_output": capture_output,
                    "timeout": timeout,
                    "check": check,
                }
            )
            return subprocess.CompletedProcess(argv, 0, stdout='{"period_summary":"agent"}', stderr="")

        adapter = HermesAgentCliAdapter("hermes-agent reflect --json", timeout_seconds=12, runner=runner)

        result = adapter.generate_reflection("system", "user", {"days": 7})

        self.assertEqual(result.provider, "hermes-agent")
        self.assertEqual(result.response["period_summary"], "agent")
        self.assertEqual(calls[0]["argv"], ["hermes-agent", "reflect", "--json"])
        self.assertEqual(calls[0]["timeout"], 12)
        self.assertTrue(calls[0]["payload"]["constraints"]["human_approval_required"])
        self.assertTrue(calls[0]["payload"]["constraints"]["do_not_apply_patches"])
        self.assertEqual(calls[0]["payload"]["context"]["days"], 7)

    def test_hermes_agent_cli_rejects_bad_json(self):
        def runner(argv, input, text, capture_output, timeout, check):
            return subprocess.CompletedProcess(argv, 0, stdout="not-json", stderr="")

        adapter = HermesAgentCliAdapter(runner=runner)

        with self.assertRaises(ReflectionAdapterError):
            adapter.generate_reflection("system", "user", {})

    def test_fallback_adapter_uses_custom_when_primary_fails(self):
        adapter = FallbackReflectionAdapter(FailingAdapter(), StaticAdapter())

        result = adapter.generate_reflection("system", "user", {})

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.provider, "static")
        self.assertEqual(result.response["period_summary"], "fallback")
        self.assertIn("failing failed", result.warnings[0])


if __name__ == "__main__":
    unittest.main()
