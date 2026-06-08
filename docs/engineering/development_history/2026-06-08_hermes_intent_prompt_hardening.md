# 2026-06-08 Hermes Intent Prompt Hardening

## Background

Hermes reviewed the daily `reading.recommend.intent` prompt and confirmed that its route boundary is correct: Hermes should act as a non-interactive profile decision layer, while `ai-reading-coach` remains the only component that writes SQLite, files, native USER memory, and outbound messages.

The review also identified two operational risks:

- Daily intent context can become noisy when applied reflection history repeats the same themes.
- Theme generation needs stricter constraints so the system does not drift back toward engineering, business, productivity, or tool-book topics when the user profile supports literature and classic science fiction.

## Decisions

- Keep `reading.recommend.intent` on the existing `themes_v1` schema to avoid downstream migration.
- Make the slot order explicit in prompt rules: first two themes are `profile_fit`, third is `exploration`.
- Require at least one literature/classics theme and at least one classic science fiction theme when supported by profile evidence.
- Downrank software engineering and AI Agent commercialization when recent history shows frequency fatigue and no fresh positive feedback.
- Pass a compact `effective_profile_summary` to Hermes before the bounded raw `profile_context`.
- Keep all side effects forbidden on the intent route. ARC remains the sole writer for SQLite, files, native USER memory, delivery channels, and patches.

## Implementation

- Added shared `THEME_GENERATION_RULES` in `app/daily_agent_adapter.py`.
- Updated Hermes `reading.recommend.intent` payload with:
  - explicit read-only system prompt,
  - `effective_profile_summary`,
  - bounded raw profile context,
  - expanded no-side-effect constraints including files, memories, and network channels.
- Reused the same theme rules in the legacy LLM theme branch so provider changes do not weaken behavior.
- Added tests for Hermes payload constraints, effective profile summary extraction, and legacy prompt rule inclusion.

## Verification

```bash
python3 -m unittest tests.test_daily_agent_adapter \
  tests.test_workflow.WorkflowTests.test_daily_run_includes_applied_memory_files_in_theme_and_recommendation_prompts \
  tests.test_workflow.WorkflowTests.test_daily_run_includes_recommendation_history_context_in_prompts

python3 -m unittest discover -s tests
```

Result: 144 tests OK.

`pytest` was not available in the current environment, so verification used the repository's `unittest` suite.
