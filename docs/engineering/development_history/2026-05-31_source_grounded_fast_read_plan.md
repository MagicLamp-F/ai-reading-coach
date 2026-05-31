# 2026-05-31 Source Grounded Fast Read Plan

Plan id: `2026-05-31_source_grounded_fast_read`
Progress document: `docs/engineering/development_history/2026-05-31_source_grounded_fast_read_progress.md`

## Background

The current Hermes fast read pack is generated from recommendation metadata, source URL, profile context, and Hermes model knowledge. It is better than fallback, but still feels like a refined summary because the system does not yet persist actual book source material such as official page text, table of contents, public descriptions, samples, interviews, or reviews.

The user agreed to start without OpenClaw. The first step is a lightweight source collector inside `ai-reading-coach`.

## Goal

Add a source-grounded path:

```text
recommendation
  -> collect public source material
  -> store book_sources
  -> generate reading.fast_read_pack with sources in context
  -> link reading_pack_sources
  -> Feishu shows richer preview
```

## Scope

In scope:

- `book_sources` table.
- `reading_pack_sources` join table.
- Lightweight HTTP source collector for the recommendation `source_url`.
- Source excerpts passed into Hermes fast-read generation.
- Tests and docs.

Out of scope:

- OpenClaw installation.
- Browser automation.
- Search API expansion.
- Public reading-pack web page.
- Copyright-protected full-text ingestion.

## Safety

- Do not print secrets.
- Do not fetch arbitrary URLs from model output beyond stored `source_url` in recommendations.
- Use HTTP timeouts.
- Store only extracted page text snippets and metadata.
- Hermes receives sanitized source excerpts, not server credentials.

## Acceptance Criteria

- Sources are persisted before pack generation when a source URL exists.
- Reading packs link to the source ids they used.
- Hermes prompt context includes source excerpts.
- If source fetch fails, pack generation still proceeds with metadata and records no fatal error.
- Tests pass.

