# 2026-05-31 Source Aware Candidate Ranking Plan

Plan id: `2026-05-31_source_aware_candidate_ranking`
Progress document: `docs/engineering/development_history/2026-05-31_source_aware_candidate_ranking_progress.md`

## Background

Tavily source grounding v1.1 can enrich already-selected recommendations, but the user wants the best result, not a visible downgrade after a weak recommendation has already been chosen.

The next step is to check source quality before final daily recommendations are selected.

## Goal

Implement candidate-pool ranking v1:

```text
Hermes/profile themes
  -> generate candidate books
  -> upsert candidate books
  -> collect Tavily/public sources
  -> score source coverage
  -> record selected/rejected candidates
  -> recommend source-qualified books only
```

## Scope

In scope:

- Add `recommendation_candidates` table.
- Add repository methods to persist candidate score, source status, final status, and reject reason.
- Add source-aware workflow branch.
- Add settings:
  - `SOURCE_AWARE_RECOMMENDATIONS`
  - `SOURCE_AWARE_STRICT_MODE`
  - `SOURCE_AWARE_CANDIDATE_COUNT`
  - `SOURCE_MIN_COVERAGE_SCORE`
  - `SOURCE_AWARE_ALLOW_LIMITED_FILL`
- Ask Hermes for a larger candidate set when `hermes-agent` is enabled.
- Score candidates with source coverage before final recommendation insert.
- Do not silently backfill low-source candidates in strict mode.
- Tests and docs.

Out of scope:

- OpenClaw.
- Google Books/Open Library adapters.
- Local EPUB/PDF import.
- Full-book chunking.

## Default Policy

Defaults favor quality:

```text
SOURCE_AWARE_RECOMMENDATIONS=true
SOURCE_AWARE_STRICT_MODE=true
SOURCE_AWARE_CANDIDATE_COUNT=6
SOURCE_MIN_COVERAGE_SCORE=0.5
SOURCE_AWARE_ALLOW_LIMITED_FILL=false
```

If fewer than 3 candidates qualify, daily sends fewer recommendations and records a warning rather than pretending weak-source candidates are high-quality.

## Acceptance Criteria

- Candidate rows are persisted with selected/rejected status.
- Final recommendations prefer source-qualified books.
- Strict mode does not silently fill low-source candidates.
- Existing non-source-aware tests still pass.
- Full test suite passes.
