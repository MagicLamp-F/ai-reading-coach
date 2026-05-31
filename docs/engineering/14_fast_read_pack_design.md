# Fast Read Pack Design

## Why

The current recommendation message answers "why this book may fit you", but not "what the book actually says". The user needs a middle layer between a short recommendation reason and full-book reading: enough content structure, argument detail, examples, and application questions to feel like they have passed through the book once.

The goal is not to copy a full book. The goal is to build a legal, structured, source-aware reading guide that helps the user decide whether to read, what to read first, and what ideas to take away.

## What To Build

Add a `reading.fast_read_pack` MVP:

```text
existing recommendation
  -> load book/recommendation/profile/memory/feedback context
  -> collect and persist public source excerpts when a source URL exists
  -> generate structured fast read pack
  -> save SQLite metadata
  -> save Markdown artifact
  -> expose CLI for manual generation
```

The first version supports both automatic daily generation and manual regeneration. By default, `run-daily` generates a pack for each recommendation and includes a concise preview in the Feishu card. Manual regeneration remains available through CLI.

## Pack Structure

Each pack should include:

- why this book was recommended to the user;
- one-sentence thesis;
- the problem the author is solving;
- the core argument chain;
- chapter or part map when available;
- core concepts and models;
- important examples or cases;
- what to read in 10 minutes, 30 minutes, and 2 hours;
- what can probably be skipped first;
- likely limitations or opposing views;
- connections to the user's current goals and blind spots;
- five self-test questions;
- source and copyright notes.

## Data Model

SQLite remains the structured source of truth.

`book_sources` stores:

- book id;
- source type, currently `official_page`;
- URL and page title;
- sanitized public text excerpt;
- fetch metadata such as status, final URL, content type and collector version.

`reading_pack_sources` links each generated pack to the source rows used in its prompt.

`reading_packs` stores:

- recommendation id;
- book id;
- artifact id;
- status;
- pack format/schema version;
- title and summary;
- route name;
- generator/provider;
- content JSON for future pages;
- error message if generation failed.

`artifacts` stores:

- artifact type;
- title;
- path;
- sha256;
- content type;
- metadata JSON.

The filesystem stores long Markdown:

```text
library/
  YYYY/
    MM/
      YYYY-MM-DD__book-title/
        reading-pack.md
```

## Source-Grounded Generation

The first source-grounded version intentionally avoids OpenClaw and browser automation. The flow is:

```text
recommendation.source_url
  -> BookSourceCollector
  -> safe HTTP GET with timeout and localhost/private-IP guard
  -> strip script/style/html
  -> store excerpt in book_sources
  -> include excerpt in Hermes reading.fast_read_pack prompt
  -> link reading_pack_sources
```

This does not fetch full books, paywalled content, private network resources, or arbitrary URLs invented during generation. If source fetching fails, the pack still generates from recommendation/profile context and records no fatal run error.

## Failure Policy

Fast read pack generation must not block daily recommendations.

- Manual CLI failure exits non-zero if the recommendation is missing.
- Model failure should produce a deterministic fallback pack from existing recommendation data where possible.
- Source fetching failure must not block pack generation.
- In `run-daily`, unexpected pack failures are recorded as run warnings and the recommendation still sends without a pack preview.
- In manual CLI mode, database or artifact write errors fail the command clearly.
- No reflection draft is approved or applied.
- Feishu sends a concise preview only; the long artifact remains in `library/.../reading-pack.md`.

## Hermes Route Direction

The product route name is:

```text
reading.fast_read_pack
```

The current MVP stores this route in SQLite and supports Hermes route generation. Set `READING_PACK_PROVIDER=hermes-agent` to generate `reading.fast_read_pack` through Hermes instead of the legacy model branch.

Daily recommendation generation already has a Hermes route branch:

```text
reading.recommend.intent
reading.recommend.generate
```

The real test `run_id=28` used Hermes for both daily recommendations and fast read packs.

```text
ai-reading-coach
  -> route adapter
  -> Hermes wrapper
  -> model/tool runtime
  -> JSON/Markdown output
```

## Acceptance Criteria

- A pack can be generated from an existing recommendation id.
- `run-daily` automatically generates packs when `DAILY_READING_PACKS_ENABLED=true`.
- Feishu recommendation cards include a fast read preview when available.
- Pack metadata is queryable from SQLite.
- Public source excerpts used by a pack are queryable from SQLite through `reading_pack_sources`.
- Long Markdown is saved as an artifact.
- Tests cover DB schema, source persistence, generator fallback, source prompt inclusion, and CLI-facing service behavior.
- Existing daily recommendation and reflection tests still pass.

## Operations

Automatic daily reading packs are enabled by default:

```env
DAILY_READING_PACKS_ENABLED=true
READING_PACK_PROVIDER=hermes-agent
READING_PACK_LIBRARY_DIR=library
```

Rollback:

```env
DAILY_READING_PACKS_ENABLED=false
```

Manual generation remains:

```bash
python3 -m app.cli generate-reading-pack --recommendation-id <id>
```
