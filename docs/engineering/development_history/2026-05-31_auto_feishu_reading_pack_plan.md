# 2026-05-31 Auto Feishu Reading Pack Plan

Plan id: `2026-05-31_auto_feishu_reading_pack`
Progress document: `docs/engineering/development_history/2026-05-31_auto_feishu_reading_pack_progress.md`
Previous related plan: `2026-05-31_fast_read_pack`

## Background

The first fast read pack implementation created the database tables, manual CLI, and artifact writer, but it did not connect the pack to daily Feishu delivery. The user needs the daily recommendation card to include book content, not only the recommendation reason.

The user also questioned the phrase "LLM client". In this codebase, `app/llm.py` is the existing model API wrapper used before Hermes was installed. It is not a separate product component. The target architecture should still keep `ai-reading-coach` as the business orchestrator and gradually move intelligent routes behind Hermes-compatible adapters.

## Goal

When `run-daily` creates each recommendation:

- generate a `reading.fast_read_pack` automatically;
- store the pack in SQLite and as Markdown artifact;
- include a concise fast read preview in the Feishu recommendation card;
- degrade safely if generation fails;
- keep feedback buttons, profile writeback, reflection approval, and daily recommendation fallback intact.

## Scope

In scope:

- Settings for enabling/disabling daily reading packs.
- Workflow integration after recommendation insert and before Feishu send.
- Lark card preview section.
- Tests for daily automatic pack generation and Lark rendering.
- Documentation updates.

Out of scope:

- Public web page for reading pack artifact.
- Feishu file upload.
- Hermes fast-read route implementation.
- OpenClaw installation.

## Design

```text
run-daily
  -> generate recommendation draft
  -> insert recommendations row
  -> if daily reading packs enabled:
       FastReadPackService.generate_for_recommendation(recommendation_id)
       -> reading_packs/artifacts rows
       -> library/.../reading-pack.md
       -> preview object
     on failure:
       record run warning
       continue without preview
  -> send Feishu recommendation card with feedback buttons and optional preview
```

The Feishu card should include:

- one-sentence thesis;
- 10-minute route;
- first 1-2 core argument points;
- artifact path for server-side lookup.

## Rollback

Set:

```env
DAILY_READING_PACKS_ENABLED=false
```

This disables automatic pack generation while preserving manual CLI generation.

## Acceptance Criteria

- `run-daily` creates reading pack rows when enabled.
- Feishu card includes fast read preview when generation succeeds or falls back.
- If pack generation raises unexpectedly, daily recommendation still sends.
- Full test suite passes.

