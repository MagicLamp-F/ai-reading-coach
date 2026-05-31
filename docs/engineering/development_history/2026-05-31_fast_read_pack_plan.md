# 2026-05-31 Fast Read Pack Implementation Plan

Plan id: `2026-05-31_fast_read_pack`
Progress document: `docs/engineering/development_history/2026-05-31_fast_read_pack_progress.md`

## Background

Current daily recommendations explain why a book is recommended, but they do not give enough of the book's actual argument, structure, concepts, examples, and reading path. The next product step is to generate a "fast read pack" so the user can quickly understand what the book says without reading the full book.

The pack must not replace careful reading or reproduce copyrighted books. It should be a structured, source-aware guide built from recommendation metadata, legal/public context, existing search snippets, and model synthesis.

## Goal

Add an MVP `reading.fast_read_pack` workflow that:

- accepts an existing recommendation id;
- loads book, recommendation, profile, memory, and recent feedback context;
- generates a Markdown fast read pack;
- stores structured metadata in SQLite for future business pages;
- writes the long Markdown artifact to `library/YYYY/MM/YYYY-MM-DD__book-title/reading-pack.md`;
- keeps daily recommendation, Feishu push, SQLite profile, feedback writeback, and reflection approval unchanged.

## Scope

In scope:

- DB tables for reading packs and artifacts.
- Repository methods for loading recommendation context and storing generated packs.
- A focused generator service using the existing LLM client with deterministic fallback.
- CLI command for manual generation.
- Documentation and tests.

Out of scope:

- OpenClaw installation.
- Dockerization.
- Web business page.
- Feishu card redesign.
- Automatic generation inside `run-daily`.
- Hermes route protocol implementation beyond documenting the intended route.

## Proposed Files

- `agent.md`: add default rule for plan/progress docs before implementation.
- `docs/engineering/development_history/2026-05-31_fast_read_pack_plan.md`: this plan.
- `docs/engineering/development_history/2026-05-31_fast_read_pack_progress.md`: current progress and verification log.
- `docs/engineering/14_fast_read_pack_design.md`: product and engineering design.
- `app/db.py`: add `artifacts` and `reading_packs` tables.
- `app/repository.py`: add data contracts and persistence/query methods.
- `app/reading_pack.py`: new generator/service for fast read packs.
- `app/cli.py`: add manual CLI command.
- `docs/engineering/04_implementation_roadmap.md`: update next milestone.
- `docs/engineering/12_hermes_memory_agent_platform.md`: mark fast read pack MVP path.
- `tests/test_reading_pack.py`: focused unit tests.

## Implementation Steps

1. Add planning/progress docs and update the agent rule.
2. Add DB schema with indexes and non-destructive migrations.
3. Add repository methods with explicit SQL.
4. Implement pack generation and Markdown artifact writing.
5. Add CLI entrypoint: `generate-reading-pack --recommendation-id <id>`.
6. Update docs.
7. Add tests.
8. Run full test suite.

## Acceptance Criteria

- `python3 -m app.cli generate-reading-pack --recommendation-id <id>` can generate a pack for an existing recommendation.
- SQLite records the pack and artifact metadata.
- The Markdown file path is stable and deterministic.
- Failed model calls produce a useful fallback pack and do not affect `run-daily`.
- `run-daily` behavior is unchanged unless explicitly extended later.
- Full test suite passes.

