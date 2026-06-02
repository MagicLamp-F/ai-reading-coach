# 2026-05-31 Current Scope Summary Plan

Plan id: `2026-05-31_current_scope_summary`
Progress document: `docs/engineering/development_history/2026-05-31_current_scope_summary_progress.md`

## Background

After the Hermes, daily recommendation, fast read pack, Feishu, and source-grounding work, the user asked for a clear summary of what already exists and what remains to do.

The goal is to make the project state understandable without rereading all prior implementation notes.

## Goal

Create and update engineering docs that answer:

- what the system can already do;
- what is implemented but still needs real-world validation;
- what remains to build;
- where OpenClaw fits and where it does not;
- what the recommended next milestones are.

## Files

- `docs/engineering/15_current_scope_and_next_plan.md`: new concise scope summary.
- `docs/engineering/README.md`: add the new document to the reading index.
- `docs/engineering/10_current_progress_summary.md`: link the new summary and refresh next-step framing.
- `docs/engineering/development_history/2026-05-31_current_scope_summary_plan.md`: this plan.
- `docs/engineering/development_history/2026-05-31_current_scope_summary_progress.md`: implementation progress and verification.

## Acceptance Criteria

- The summary separates completed capabilities, partially validated capabilities, and not-yet-started work.
- It explicitly explains that OpenClaw is useful later for complex source acquisition/tool orchestration, but is not the current blocker.
- It makes clear that the next core work is source acquisition v2, pack quality evaluation, public/business reading pages, and operational trial runs.
- No code changes are required.
