# 2026-06-07 Hermes Feedback Ingest

## Goal

让 Hermes 作为主 memory/profile 决策者处理真实阅读反馈，而不是只在 ARC 侧生成局部画像。

## Changes

- Added Hermes route usage `reading.feedback.ingest` with output schema `profile_update_v1`.
- Added `app/profile_ingest.py`:
  - sends feedback event and recommendation context to Hermes;
  - normalizes `should_update_native_memory` safely;
  - writes native USER memory only through ARC's controlled upsert.
- Added `hermes_profile_update_events` SQLite audit table.
- Wired `process_feedback()` so normal `run-daily` calls Hermes ingest before ARC `profile_items` updates.
- Added `reading_coach_hermes_profile_updates_total{status=...}` metrics.
- Added `show-hermes-profile-sync` CLI for snapshot/native USER memory diagnostics.
- Patched `/home/ubuntu/projects/hermes-agent/bin/reflect-json` to normalize `profile_update_v1`.

## Failure Boundary

- No fallback for Hermes feedback ingest.
- If Hermes ingest fails, ARC records `status='failed'`, leaves `feedback_events.processed_at` empty, and fails the run.
- Hermes route agent still cannot directly modify files or memories. ARC writes only the `[arc-reading-profile]` entry in native `USER.md`.

## Verification

Automated:

```text
python3 -m unittest tests.test_db tests.test_profile tests.test_profile_ingest tests.test_memory tests.test_metrics
36 tests OK

python3 -m unittest discover
130 tests OK
```

Real normal flow:

```text
POST /feedback/inline through python3 -m app.cli run-server --host 127.0.0.1 --port 8123
feedback_events.id=27

python3 -m app.cli run-daily
daily run_id=56 success
processed_feedback=1
recommendation_id=69: 围城 / 钱锺书
reading_pack id=40 status=generated generator_provider=hermes-agent
reflection run_id=57 success
reflection_id=8 auto-applied
```

Audit:

```text
hermes_profile_update_events.id=1
feedback_event_id=27
status=applied
should_update_native_memory=1
confidence=0.91
```

Native memory:

```text
python3 -m app.cli show-hermes-profile-sync --json
arc_entry_present=true
native_user_memory_path=/home/ubuntu/.hermes/memories/USER.md
```
