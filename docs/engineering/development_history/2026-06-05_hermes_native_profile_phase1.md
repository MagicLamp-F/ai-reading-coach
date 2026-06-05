# Hermes Native Profile Phase 1

## Plan

- Add a read-only `HermesNativeProfileProvider` for `memory/HERMES_NATIVE_PROFILE.md`.
- Fall back to `/home/ubuntu/.hermes/SOUL.md` when the ARC snapshot is absent.
- Rebuild daily and reading-pack profile context with explicit priority layers.
- Keep ARC `profile_items` as a lower-priority reading-business profile.

## Verification

- Add tests for snapshot loading, fallback behavior, prompt priority order, and reading-pack context reuse.
- Run focused unit tests before handoff.

## Outcome

- Implemented the read-only native profile provider and config knobs.
- Daily recommendations and deep read packs now share the same Priority 1-5 profile context.
- `/metrics` now exposes native profile load counts by source.
- Hermes provider paths are now strict by default: daily, reading pack, and reflection fail fast instead of silently falling back.
- `memory/HERMES_NATIVE_PROFILE.md` is generated through `reading.profile.sync_snapshot` when missing.
- Real normal-flow verification passed after fixing invalid Hermes `.env` overrides and wrapper empty-stdout recovery:
  - `daily run_id=48`: success, recommendation `活着` by `余华`, Hermes reading pack `generated`.
  - `reflection run_id=49`: success, `reflection_id=4` auto-applied.
- Important finding: current `/home/ubuntu/.hermes/SOUL.md` describes Hermes Agent identity, not the user. The provider now passes ARC structured reading profile and ARC applied memory as primary evidence when generating or refreshing the snapshot.
- Follow-up verification refreshed `memory/HERMES_NATIVE_PROFILE.md` from ARC evidence. The snapshot now includes user reading preferences for classic/high-reputation literature, science fiction, personal knowledge management, software engineering practice, and lower current priority for AI Agent commercialization.
- Updated README and `.env.example` with snapshot/fallback settings.
- Verification passed with `python3 -m unittest discover -s tests`.
