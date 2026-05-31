# Agent Rules

- The user's API relay may switch account pools at any time. Minimize impact on the project session by treating the repository state as the source of truth, avoiding reliance on account-specific or ephemeral session state, keeping changes incremental and recoverable, and briefly re-checking context before continuing after any interruption or identity/model change.
- After a方案 is confirmed and before implementation, first create or update a planning document and an in-progress status document under `docs/engineering/development_history/`. The two documents should reference each other with a stable plan id, record the planned work, implementation progress, verification results, and final outcome so the project history can be reviewed later.
