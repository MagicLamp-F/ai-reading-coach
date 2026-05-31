# 2026-05-31 Hermes Fast Read Feishu Plan

Plan id: `2026-05-31_hermes_fast_read_feishu`
Progress document: `docs/engineering/development_history/2026-05-31_hermes_fast_read_feishu_progress.md`

## Background

The user received Feishu recommendations, but the fast read pack was a fallback placeholder because the daily test disabled the legacy project model key to prove recommendation generation used Hermes. The reading pack generation still used the legacy model branch, so it fell back.

The Feishu card also showed a server-local Markdown path, which is not directly readable from Feishu.

## Goal

- Generate `reading.fast_read_pack` through Hermes route.
- Store the full pack in SQLite and Markdown as before.
- Show a richer fast-read preview directly inside the Feishu card.
- Keep the local artifact path as machine archive only, not the user-facing reading entry.

## Scope

In scope:

- Hermes reading pack adapter.
- Wrapper schema handling for `fast_read_pack_v1`.
- Feishu preview expansion.
- Real Feishu push test.

Out of scope:

- Public web page for full reading pack.
- Feishu file upload.
- OpenClaw.

## Acceptance Criteria

- Reading pack status is `generated`, not `fallback`, when Hermes route succeeds.
- Feishu card includes thesis, problem, route, core points, concepts, chapter/part map, and examples/limitations preview.
- `run-daily` with Hermes daily provider can send visible fast-read content to Feishu.

