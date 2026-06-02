# 2026-05-31 Tavily Source Grounding Progress

Plan id: `2026-05-31_tavily_source_grounding`
Plan document: `docs/engineering/development_history/2026-05-31_tavily_source_grounding_plan.md`

## Current Status

Status: completed.

## Progress Log

- Created mapped plan/progress documents before implementation.
- Added Tavily API key file loading with `TAVILY_API_KEY_FILE`, defaulting to `/home/ubuntu/.config/tavily/api_key`.
- Extended `BookSourceCollector` to search by recommendation title/author through Tavily, fetch public result pages, classify source types, and store excerpts in `book_sources`.
- Added source quality computation: `source_rich`, `source_usable`, `source_limited`, `source_missing`.
- Added source quality to reading pack JSON/Markdown and Feishu preview.
- Split source-page fetching into a shorter timeout HTTP client to avoid Tavily results that are unreachable from Tencent Cloud delaying the whole workflow.
- Upgraded Tavily enrichment to use advanced search, three source-intent queries per book, and Tavily `raw_content` before local page fetching.
- Added clean text length into source coverage scoring so large usable public excerpts do not remain incorrectly labeled as `source_limited`.
- Added tests for key file loading, Tavily search enrichment, source quality, reading pack source quality, and Lark rendering.
- Ran a real Tavily smoke search without printing the API key.

## Files Changed

- `docs/engineering/development_history/2026-05-31_tavily_source_grounding_plan.md`
- `docs/engineering/development_history/2026-05-31_tavily_source_grounding_progress.md`
- `app/config.py`
- `app/factory.py`
- `app/source_collector.py`
- `app/reading_pack.py`
- `app/lark.py`
- `tests/test_config.py`
- `tests/test_source_collector.py`
- `tests/test_reading_pack.py`
- `tests/test_lark.py`
- `docs/engineering/10_current_progress_summary.md`
- `docs/engineering/15_current_scope_and_next_plan.md`

## Verification

```bash
python3 -m py_compile app/config.py app/source_collector.py app/reading_pack.py app/lark.py app/factory.py
python3 -m unittest tests.test_config tests.test_source_collector tests.test_reading_pack tests.test_lark -q
```

Result: passed, 19 tests OK.

```bash
python3 -m unittest discover -q
```

Result: passed, 75 tests OK.

Real Tavily smoke:

```text
key_loaded True
result_count 1
title Book Review: A Philosophy of Software Design | Leo Robinovitch @ The Leo Zone
```

No API key was printed.

Real Tavily raw-content source smoke:

```text
source_count 3
quality {'status': 'source_usable', 'score': 0.6, 'source_count': 3, 'clean_text_chars': 18000, 'source_types': ['public_page', 'review']}
```

Controlled manual reading-pack smoke:

```bash
READING_PACK_PROVIDER=hermes-agent HERMES_AGENT_TIMEOUT_SECONDS=240 OPENAI_API_KEY='' \
python3 -m app.cli generate-reading-pack --recommendation-id 50 --library-dir /tmp/arc-tavily-pack
```

Result:

```text
Fast read pack generated: id=13
Status: generated
provider hermes-agent
source_quality {'status': 'source_limited', 'score': 0.2, 'source_count': 1, 'source_types': ['review']}
```

Observed:

```text
The original source URL returned HTTP 403.
Some Tavily result pages were unreachable from Tencent Cloud direct network.
The workflow still completed and marked the pack as source_limited.
```

## Outcome

Completed Tavily source grounding v1.1. The system can now enrich each already-selected recommendation with Tavily raw-content public sources and make source scarcity visible instead of silently pretending a pack is source-rich. The next major step is candidate-pool ranking before final recommendation selection.
