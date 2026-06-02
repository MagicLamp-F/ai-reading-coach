# 2026-05-31 Source Aware Candidate Ranking Progress

Plan id: `2026-05-31_source_aware_candidate_ranking`
Plan document: `docs/engineering/development_history/2026-05-31_source_aware_candidate_ranking_plan.md`

## Current Status

Status: completed.

## Progress Log

- Created mapped plan/progress documents before implementation.
- Added `recommendation_candidates` table.
- Added repository persistence for candidate status, scores, source status, and reject reasons.
- Added source-aware workflow settings and strict-mode ranking.
- Updated Hermes daily adapter so the workflow can ask for a larger candidate set.
- Added source-aware candidate scoring before final recommendation insert.
- Strict mode now selects fewer than 3 books if fewer than 3 candidates pass `SOURCE_MIN_COVERAGE_SCORE`, instead of silently filling weak-source books.
- Added tests for candidate table creation and strict source-aware selection.

## Files Changed

- `docs/engineering/development_history/2026-05-31_source_aware_candidate_ranking_plan.md`
- `docs/engineering/development_history/2026-05-31_source_aware_candidate_ranking_progress.md`
- `app/db.py`
- `app/repository.py`
- `app/config.py`
- `app/factory.py`
- `app/daily_agent_adapter.py`
- `app/source_collector.py`
- `app/workflow.py`
- `tests/test_db.py`
- `tests/test_workflow.py`

## Verification

```bash
python3 -m py_compile app/db.py app/repository.py app/daily_agent_adapter.py app/source_collector.py app/workflow.py app/factory.py app/config.py
python3 -m unittest tests.test_db tests.test_workflow tests.test_daily_agent_adapter -q
```

Result: passed.

```bash
python3 -m unittest discover -q
```

Result: passed, 76 tests OK.

Controlled source-aware daily smoke:

```bash
DATABASE_URL=sqlite:////tmp/arc_source_aware_smoke.db \
LARK_WEBHOOK_URL='' \
OPENAI_API_KEY='' \
DAILY_RECOMMENDATION_PROVIDER=hermes-agent \
DAILY_READING_PACKS_ENABLED=false \
SOURCE_AWARE_RECOMMENDATIONS=true \
SOURCE_AWARE_CANDIDATE_COUNT=4 \
SOURCE_SEARCH_MAX_RESULTS=1 \
SOURCE_SEARCH_QUERIES_PER_BOOK=2 \
HERMES_AGENT_TIMEOUT_SECONDS=240 \
python3 -m app.cli run-daily
```

Result:

```text
run_id=1
recommendations=2
candidates=3
selected:
- 人生效率手册 source_usable score=0.57
- 运营前线 source_usable score=0.61
rejected:
- 经营者养成笔记 source_limited score=0.4 reject_reason=source_coverage_below_threshold
```

Observed:

```text
Strict mode selected fewer than 3 books because only 2 candidates passed the source threshold.
Lark was disabled for the smoke and no Feishu message was sent.
```

Real daily run on 2026-06-01:

```text
run_id=32
status=success
api_calls=3
warning_message=None
candidates=3
selected=3
candidate source_status=source_rich for all selected candidates
reading_packs=3
reading_pack status=generated
reading_pack provider=hermes-agent
```

Selected candidates:

```text
- Building Evolutionary Architectures, source_rich, score=1.0
- 软件架构实践（原书第4版）, source_rich, score=0.93
- Fundamentals of Software Architecture, source_rich, score=0.83
```

After the run, one reading pack initially showed lower source quality because the pack generator only loaded the latest 3 sources. The service was corrected to load up to 10 sources and include up to 6 source excerpts in the prompt. A controlled regeneration for recommendation `54` produced:

```text
reading_pack_id=19
status=generated
provider=hermes-agent
source_quality=source_rich
score=0.93
source_count=8
```

## Outcome

Completed source-aware candidate ranking v1. The daily flow can now persist candidate books, score source quality before final recommendation insertion, and avoid silently filling weak-source books in strict mode.
