# 2026-06-07 Recommendation History, Hermes Session, and Web Facade

## Plan

- Enhance `RecommendationHistoryContext` so Hermes receives more actionable recency, repeated-title, feedback, fatigue, and instruction context.
- Inspect the local Hermes route wrapper for controllable short session/thread support. If supported, wire a bounded local `run-daily` session; if not, document the explicit-context fallback.
- Replace the `8010` root placeholder with a mobile-compatible facade page for daily reading operations.
- Update `agent.md` and public docs so future sessions preserve the current architecture boundary.
- Verify with unit tests, web build, Hermes profile sync, and a real `run-daily`, then commit without runtime memory files.

## Progress

- Started from repository state only. Existing dirty files are runtime memory artifacts under `memory/` and must stay out of the commit.
- Enhanced `build_recommendation_history_context()` with:
  - window summary;
  - hard exclusions;
  - recent exact-title cooldown;
  - negative, neutral, and positive feedback sections;
  - feedback type/reason distribution;
  - repeated exact-title and theme fatigue signals;
  - positive/negative theme signals;
  - explicit Hermes selection instructions.
- Added unit coverage for the enhanced history context.
- Inspected `/home/ubuntu/projects/hermes-agent/bin/reflect-json`.
  - It calls Hermes with `--oneshot`.
  - It does not accept or expose a controllable session/thread id.
  - It disables `session_search` in its generated safe config.
  - Therefore the implemented short local chain is ARC-explicit `local_session` context, not Hermes internal thread state.
- Added bounded `local_session` context to `HermesDailyRecommendationAdapter`.
  - `run-daily` starts a session after creating the run id.
  - `reading.recommend.intent` records the generated themes.
  - `reading.recommend.generate` receives the previous local turn explicitly in payload context.
  - The session is cleared in `finally`.
- Replaced the React root placeholder with a mobile-compatible facade page and generated a project hero image at `web/public/assets/reading-coach-hero.png`.
- Updated `README.md`, `docs/README.md`, `docs/architecture_overview.md`, and `agent.md`.

## Verification So Far

```bash
python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow
cd web && npm run build
```

Results:

- 20 backend tests OK for targeted adapter/workflow coverage.
- Web TypeScript and Vite production build OK.

## Final Verification

```bash
python3 -m unittest discover
/home/ubuntu/projects/hermes-agent/bin/reflect-json --check-env
python3 -m app.cli show-hermes-profile-sync --json
python3 -m app.cli run-daily
curl -I http://127.0.0.1:8011/assets/reading-coach-hero.png
```

Results:

- 135 Python tests OK.
- Hermes wrapper check-env found the Hermes binary and `OPENAI_API_KEY` was set; no secret values were printed.
- Hermes native profile sync reported `arc_entry_present=true` in `/home/ubuntu/.hermes/memories/USER.md`.
- Real `run-daily` completed successfully with `run_id=60`.
  - Recommendation generated: `黑暗的左手` / `厄休拉·勒古恩`.
  - Automatic reflection completed and applied: `reflection_id=10`.
  - Source collection emitted network warnings for unreachable external pages, but the run completed.
- Vite served the generated hero image successfully from `/assets/reading-coach-hero.png`.

## Commit Boundary

- Include code, tests, docs, and `web/public/assets/reading-coach-hero.png`.
- Exclude runtime memory mutations under `memory/`, including `memory/USER.md`, `memory/MEMORY.md`, `memory/HERMES_NATIVE_PROFILE.md`, and `memory/change_logs/`.
