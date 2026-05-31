# 2026-05-31 Source Grounded Fast Read Progress

Plan id: `2026-05-31_source_grounded_fast_read`
Plan document: `docs/engineering/development_history/2026-05-31_source_grounded_fast_read_plan.md`

## Current Status

Status: completed.

## Progress Log

- Created mapped plan/progress documents before implementation.
- Added SQLite `book_sources` and `reading_pack_sources` tables.
- Added repository methods for source upsert, listing, and reading-pack/source linking.
- Added `HttpClient.get_text()` for bounded public text fetches.
- Added `BookSourceCollector` to fetch recommendation `source_url`, block localhost/private IP literals, strip HTML/script/style, normalize text, and store excerpts.
- Wired `FastReadPackService` to load or collect sources before generation, include excerpts in the Hermes prompt context, store `source_refs` in pack JSON, and link used source ids.
- Wired `run-daily` and manual `generate-reading-pack` to use the source collector.
- Updated architecture, roadmap, current-progress, and fast-read design docs.
- Ran real Hermes daily + Hermes reading-pack flow after the source layer change.

## Files Changed

- `docs/engineering/development_history/2026-05-31_source_grounded_fast_read_plan.md`
- `docs/engineering/development_history/2026-05-31_source_grounded_fast_read_progress.md`
- `app/db.py`
- `app/repository.py`
- `app/http_client.py`
- `app/source_collector.py`
- `app/reading_pack.py`
- `app/workflow.py`
- `app/factory.py`
- `app/cli.py`
- `tests/test_db.py`
- `tests/test_source_collector.py`
- `tests/test_reading_pack.py`
- `docs/engineering/01_system_architecture.md`
- `docs/engineering/04_implementation_roadmap.md`
- `docs/engineering/10_current_progress_summary.md`
- `docs/engineering/14_fast_read_pack_design.md`

## Verification

```bash
python3 -m py_compile app/db.py app/repository.py app/http_client.py app/source_collector.py app/reading_pack.py app/workflow.py app/factory.py
python3 -m unittest tests.test_db tests.test_source_collector tests.test_reading_pack -q
```

Result: passed, 12 tests OK.

```bash
python3 -m py_compile app/cli.py app/factory.py app/workflow.py app/reading_pack.py app/source_collector.py
python3 -m unittest discover -q
```

Result: passed, 70 tests OK.

Real Hermes + Feishu daily smoke:

```bash
DAILY_RECOMMENDATION_PROVIDER=hermes-agent \
READING_PACK_PROVIDER=hermes-agent \
HERMES_AGENT_TIMEOUT_SECONDS=240 \
OPENAI_API_KEY='' \
python3 -m app.cli run-daily
```

Result:

```text
run_id=29
status=success
recommendations_count=3
reading_packs_count=3
reading_pack_status=generated
generator_provider=hermes-agent
api_calls=0
reading_pack_source_links=2
```

Observed one non-fatal source fetch warning:

```text
Book source fetch returned HTTP 403 for one book source URL
```

This matched the failure policy: source fetch failed for that one URL, but daily recommendation, Hermes generation, SQLite writes, and Feishu send path still completed.

## Outcome

Completed the first source-grounded fast-read layer. The pack quality is now able to use real public page excerpts when the recommendation source URL is accessible. It is still not a full book-ingestion system: no OpenClaw, no browser automation, no paywalled/full-text capture, and no public reading-pack page yet.
