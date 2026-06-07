# Agent Rules

- The user's API relay may switch account pools at any time. Minimize impact on the project session by treating the repository state as the source of truth, avoiding reliance on account-specific or ephemeral session state, keeping changes incremental and recoverable, and briefly re-checking context before continuing after any interruption or identity/model change.
- Documentation should be proportional to task size to control token usage. For small fixes, inspections, command runs, and narrow follow-ups, do not create or update `docs/engineering/development_history/` files by default; instead, summarize the change and verification briefly in the final response.
- For substantial implementation work, architecture changes, multi-step experiments, or user-confirmed方案 work, create or update one concise planning/status record under `docs/engineering/development_history/` before implementation. Prefer a single compact document unless the work genuinely needs separate plan and progress files. Record the plan id if used, the intended change, key progress, verification, and final outcome.
- Minimize context and command output by default: use `rg` to locate relevant code before reading files, read only targeted file ranges, avoid whole-repository scans unless necessary, and cap long logs/test output to the failure summary and actionable lines.
- Keep routine assistant responses concise unless the user asks for detailed reasoning, a full plan, or a document-style explanation.

## Current Architecture Decisions

- Hermes native `/home/ubuntu/.hermes/memories/USER.md` is the primary reading-profile memory source. ARC manages only the `[arc-reading-profile]` entry in that file.
- `memory/HERMES_NATIVE_PROFILE.md` is an ARC-local compatibility/diagnostic snapshot, not the source of truth. Do not treat it as the primary profile when changing recommendation flow.
- `run-daily` should pass explicit context to Hermes routes: Hermes native USER profile, ARC structured profile, ARC applied memory, recommendation history, feedback, and sources. Do not rely on implicit long chat history for reproducibility.
- Recommendation history belongs in SQLite, not Hermes USER memory. ARC builds `RecommendationHistoryContext` from `recommendations` and `feedback_events`; Hermes uses it for semantic selection and avoidance, while ARC remains responsible for persistence, audit, and hard validation.
- `RecommendationHistoryContext` should include more than exact exclusions: window summary, recent exact-title cooldown, feedback distribution, repeated titles/themes, positive anchors, negative/neutral signals, and explicit Hermes selection instructions.
- Feedback profile ingest must include the current Hermes native `[arc-reading-profile]` so Hermes updates the profile incrementally rather than judging a single feedback event in isolation.
- Hermes route failures in normal Hermes providers are real failures. Do not add fallback paths that hide broken Hermes behavior.
- Current `/home/ubuntu/projects/hermes-agent/bin/reflect-json` uses Hermes `--oneshot` and does not expose a controllable session/thread id. Short local Hermes chains inside one `run-daily` use ARC's explicit bounded `local_session` context instead; cross-day, cross-feedback, and cross-reflection state must be written to Hermes native memory or ARC SQLite.
- The React Web root on port `8010` is a mobile-compatible facade page. Keep it as the operational entry surface and avoid reverting it to a placeholder.
