# 2026-05-31 Tavily Source Grounding Plan

Plan id: `2026-05-31_tavily_source_grounding`
Progress document: `docs/engineering/development_history/2026-05-31_tavily_source_grounding_progress.md`

## Background

The user wants the prior source-aware recommendation and fast-read-pack proposals merged into an executable plan, but is concerned about silent fallback and token cost. They also provided a Tavily key file at `/home/ubuntu/.config/tavily/api_key` with a 1000-credit monthly budget.

The first implementation should improve source grounding without rewriting the whole recommendation pipeline in one step.

## Goal

Implement source grounding v2 for the three daily recommended books:

```text
recommendation
  -> source_url fetch
  -> Tavily search by title/author
  -> fetch top public pages
  -> classify source type
  -> store source excerpts
  -> compute source coverage
  -> include source quality in reading pack and Feishu preview
```

## Scope

In scope:

- Read Tavily API key from `TAVILY_API_KEY` or a secret file path.
- Add source collector search enrichment using the existing `TavilySearch`.
- Store Tavily-found pages in `book_sources`.
- Compute and expose `source_coverage_score`, source count, and source status.
- Make source quality visible in Feishu and reading pack JSON/Markdown.
- Record source scarcity explicitly instead of silently pretending the pack is source-rich.
- Tests and docs.

Out of scope for this first step:

- Full 15-30 candidate pool selection.
- Google Books/Open Library adapters.
- OpenClaw.
- Local EPUB/PDF import.
- Full-book chunking.

## Fallback Policy

No silent fallback:

- If Tavily key is absent, source search is disabled and this is reflected by source quality.
- If Tavily returns no useful pages, the reading pack still generates, but source status is `source_limited` or `source_missing`.
- If one page returns 403/timeout, that page is skipped; other sources continue.
- Daily recommendation must not fail because source enrichment fails.

## Tavily Credit Budget

Use basic search only.

Initial default:

```text
3 Tavily searches per recommended book
max 3 results per query
search depth: advanced
include raw_content: true
daily cost: about 9 source searches/day for 3 recommendations
1000 credits/month: enough for roughly 50-110 daily runs depending on Tavily's exact advanced-search credit cost
source page fetch timeout: 6 seconds
source page fetch retries: 0
```

This is conservative and can be raised later.

## Acceptance Criteria

- `TAVILY_API_KEY_FILE=/home/ubuntu/.config/tavily/api_key` can enable Tavily without printing the key.
- Source collector fetches Tavily result pages for a recommendation.
- Reading pack content includes `source_quality`.
- Feishu preview shows source status and coverage.
- If Tavily is disabled or fails, tests prove source status is visible and daily generation still works.
- Full test suite passes.
