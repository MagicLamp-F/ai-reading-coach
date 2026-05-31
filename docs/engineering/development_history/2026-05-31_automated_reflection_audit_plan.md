# 2026-05-31 Automated Reflection Audit Plan

Plan id: `2026-05-31_automated_reflection_audit`
Progress document: `docs/engineering/development_history/2026-05-31_automated_reflection_audit_progress.md`

## Background

The original reflection design required manual `approve-reflection` and `apply-reflection` before writing to `memory/USER.md` and `memory/MEMORY.md`. The user now wants the chain to be automatable, with a durable machine-side change record instead of mandatory human approval.

The updated principle is:

```text
automation is allowed,
but every memory mutation must leave an audit artifact.
```

## Goal

Add an automatic reflection apply path that:

- can be enabled by CLI flag or env config;
- moves a generated reflection from draft to approved to applied automatically;
- appends patches to `memory/USER.md` and `memory/MEMORY.md`;
- writes a daily audit/change-log file under `memory/change_logs/`;
- keeps manual approval commands available as a rollback/inspection path;
- does not give Hermes direct write access to files or SQLite.

## Scope

In scope:

- `generate-reflection --auto-apply`
- `HERMES_REFLECTION_AUTO_APPLY`
- change-log artifact creation
- Lark summary text for auto-applied reflections
- tests and docs

Out of scope:

- Changing daily recommendation model calls to Hermes routes.
- Rewriting all AI calls behind Hermes in this step.
- OpenClaw.

## Audit File

Path:

```text
memory/change_logs/YYYY-MM-DD_reflection_<id>_<mode>.md
```

Content:

- reflection id;
- mode: manual or auto;
- applied timestamp;
- period;
- summary;
- USER.md patch;
- MEMORY.md patch.

## Acceptance Criteria

- Manual approve/apply still works.
- `generate-reflection --auto-apply` writes memory files and audit file.
- Auto-applied reflection status is `applied`.
- Lark summary no longer says "pending manual review" when auto-applied.
- Tests pass.

