# 2026-06-08 Hermes Intent Prompt Hardening

## Background

Hermes reviewed the daily `reading.recommend.intent` prompt and confirmed that its route boundary is correct: Hermes should act as a non-interactive profile decision layer, while `ai-reading-coach` remains the only component that writes SQLite, files, native USER memory, and outbound messages.

The review also identified two operational risks:

- Daily intent context can become noisy when applied reflection history repeats the same themes.
- Theme generation needs stricter constraints so the system does not drift back toward engineering, business, productivity, or tool-book topics when the user profile supports literature and classic science fiction.

## Decisions

- Upgrade `reading.recommend.intent` to `themes_v2` while preserving backward compatibility with legacy `themes_v1` string lists.
- Make the slot order explicit in prompt rules: first two themes are `profile_fit`, third is `exploration`.
- Require at least one literature/classics theme and at least one classic science fiction theme when supported by profile evidence.
- Downrank software engineering and AI Agent commercialization when recent history shows frequency fatigue and no fresh positive feedback.
- Pass a compact `effective_profile_summary` to Hermes before the bounded raw `profile_context`.
- Pass structured `theme_intents` into `reading.recommend.generate` so book selection sees each theme's slot and rationale.
- Keep all side effects forbidden on the intent route. ARC remains the sole writer for SQLite, files, native USER memory, delivery channels, and patches.

## Implementation

- Added shared `THEME_GENERATION_RULES` in `app/daily_agent_adapter.py`.
- Updated Hermes `reading.recommend.intent` payload with:
  - explicit read-only system prompt,
  - `effective_profile_summary`,
  - bounded raw profile context,
  - `themes_v2` output contract containing `theme`, `slot`, and `reason`,
  - expanded no-side-effect constraints including files, memories, and network channels.
- Updated `/home/ubuntu/projects/hermes-agent/bin/reflect-json` to normalize `themes_v2` and tolerate legacy string themes.
- Reused the same theme rules in the legacy LLM theme branch so provider changes do not weaken behavior.
- Added tests for Hermes payload constraints, effective profile summary extraction, and legacy prompt rule inclusion.

## Verification

```bash
python3 -m unittest tests.test_daily_agent_adapter \
  tests.test_workflow.WorkflowTests.test_daily_run_includes_applied_memory_files_in_theme_and_recommendation_prompts \
  tests.test_workflow.WorkflowTests.test_daily_run_includes_recommendation_history_context_in_prompts

python3 -m unittest discover -s tests

python3 - <<'PY'
from importlib.machinery import SourceFileLoader
m = SourceFileLoader('reflect_json', '/home/ubuntu/projects/hermes-agent/bin/reflect-json').load_module()
assert m.normalize_result({'themes': ['文学经典', '科幻经典', '探索']}, {'output_schema': 'themes_v2'})['themes'][2]['slot'] == 'exploration'
PY
```

Result: 144 tests OK.

`pytest` was not available in the current environment, so verification used the repository's `unittest` suite.
