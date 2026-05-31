# 2026-05-31 Hermes Daily Feishu Test Plan

Plan id: `2026-05-31_hermes_daily_feishu_test`
Progress document: `docs/engineering/development_history/2026-05-31_hermes_daily_feishu_test_progress.md`

## Background

The user wants a visible test where Hermes filters/generates recommendation data and `ai-reading-coach` sends the result to Feishu. The current daily workflow still has a legacy branch that calls `app/llm.py` directly for theme and recommendation generation. Hermes is already configured and can call its model successfully.

## Goal

Run one real daily recommendation test where:

- daily theme generation can use Hermes;
- recommendation generation/filtering can use Hermes;
- `ai-reading-coach` remains the business orchestrator and sends Feishu;
- model/provider config stays in Hermes, not in the business project;
- failures downgrade to deterministic fallback and do not break Feishu sending.

## Scope

In scope:

- Extend the Hermes wrapper to support route JSON, not only reflection JSON.
- Add a daily recommendation adapter using the existing Hermes command.
- Add config to switch daily recommendation provider to Hermes.
- Run route smoke tests and a real `run-daily` test.
- Explain adapter vs wrapper in concrete project terms.

Out of scope:

- OpenClaw.
- Public reading-pack page.
- Removing the legacy direct model branch entirely.

## Target Route Flow

```text
ai-reading-coach run-daily
  -> DailyRecommendationAgentAdapter
  -> HermesDailyRecommendationAdapter
  -> /home/ubuntu/projects/hermes-agent/bin/reflect-json
  -> hermes --oneshot
  -> Hermes configured model
  -> JSON themes/books
  -> SQLite recommendations
  -> reading packs
  -> Feishu card
```

## Acceptance Criteria

- Hermes route smoke returns JSON for themes.
- Hermes route smoke returns JSON for books.
- Real `run-daily` completes with `DAILY_RECOMMENDATION_PROVIDER=hermes-agent`.
- Feishu send path executes.
- SQLite contains recommendations and reading packs for the test run.

